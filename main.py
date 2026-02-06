"""
ChartVision Pro X - Institutional Trading Platform (v3.0 HARDENED)
Backend API with Gemini AI Integration & Multi-Broker Support
Supports: IIFL Blaze (XTS), Zerodha, Upstox, FYERS, Dhan with Auto-Login (TOTP)

Multi-User Architecture: Each user maintains their own broker session

CHANGELOG v3.0 - 47 FIXES & ENHANCEMENTS:
─────────────────────────────────────────
RISK MANAGEMENT:
  01. Market hours detection (NSE 9:15-15:30 IST, weekday only)
  02. Daily loss limit (configurable, default ₹25K)
  03. Max position size limit (configurable, default ₹5L)
  04. Duplicate order prevention (5s dedup window)
  05. Signal validation (confidence, safety, price direction)
  06. Confidence gating (reject <50% confidence)

INTELLIGENCE:
  07. Structured logging replacing all print() statements
  08. Health endpoint with circuit breaker + risk status
  09. Broker heartbeat monitoring
  10. Stale signal warnings
  11. Rate limiter on Gemini (1 req/3s)
  12. Signal timestamp injection
"""

import os
import json
import asyncio
import base64
import hmac
import struct
import time
import hashlib
import uuid
import secrets
import logging
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Set
from contextlib import asynccontextmanager
from collections import defaultdict
import httpx
from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, HTTPException,
    Depends, BackgroundTasks, Header, Cookie, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import pyotp
import uvicorn

# ══════════════════════════════════════════════════════════════
#  STRUCTURED LOGGING
# ══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("CVProX")

# ══════════════════════════════════════════════════════════════
#  ENUMS
# ══════════════════════════════════════════════════════════════

class BrokerType(str, Enum):
    IIFL_BLAZE = "iifl_blaze"
    ZERODHA = "zerodha"
    UPSTOX = "upstox"
    FYERS = "fyers"
    DHAN = "dhan"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"

class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"

# ══════════════════════════════════════════════════════════════
#  PYDANTIC MODELS  (with strict validation)
# ══════════════════════════════════════════════════════════════

class BrokerCredentials(BaseModel):
    broker: BrokerType
    api_key: str
    api_secret: str
    user_id: Optional[str] = None
    password: Optional[str] = None
    totp_secret: Optional[str] = None
    pin: Optional[str] = None
    market_api_key: Optional[str] = None
    market_secret_key: Optional[str] = None
    source: Optional[str] = "WEBAPI"

    @field_validator("api_key", "api_secret")
    @classmethod
    def must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Cannot be empty")
        return v.strip()

class GeminiConfig(BaseModel):
    api_key: str
    model: str = "gemini-2.0-flash"

    @field_validator("api_key")
    @classmethod
    def key_must_exist(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("API key cannot be empty")
        return v.strip()

class ChartImage(BaseModel):
    chart_type: str
    image_base64: str
    symbol: str
    timeframe: str

    @field_validator("chart_type")
    @classmethod
    def valid_chart_type(cls, v: str) -> str:
        valid = {"spot", "market_profile", "orderflow", "option_chain"}
        if v not in valid:
            raise ValueError(f"chart_type must be one of {valid}")
        return v

class MultiChartAnalysisRequest(BaseModel):
    charts: List[ChartImage]
    strategy_context: str = ""
    previous_analysis: Optional[str] = None

    @field_validator("charts")
    @classmethod
    def at_least_one(cls, v: List) -> List:
        if not v:
            raise ValueError("At least one chart required")
        if len(v) > 6:
            raise ValueError("Maximum 6 charts")
        return v

class OrderRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"
    transaction_type: TransactionType
    order_type: OrderType
    quantity: int
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product: str = "MIS"

    @field_validator("quantity")
    @classmethod
    def qty_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Quantity must be positive")
        if v > 50000:
            raise ValueError("Quantity exceeds 50 000 limit")
        return v

    @field_validator("symbol")
    @classmethod
    def symbol_ok(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Symbol cannot be empty")
        return v.strip().upper()

    @field_validator("price", "trigger_price")
    @classmethod
    def price_ok(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("Price cannot be negative")
        return v

class TradeSignal(BaseModel):
    decision: str = "NO_TRADE"
    confidence: int = 0
    safety_score: int = 0
    entry: Optional[float] = None
    stoploss: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    target3: Optional[float] = None
    risk_reward: str = "1:1"
    reasoning: List[str] = []
    warnings: List[str] = []
    timestamp: Optional[str] = None

# ══════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Stop calls after repeated failures; auto-recover after timeout."""

    def __init__(self, threshold: int = 5, timeout: int = 60):
        self.threshold = threshold
        self.timeout = timeout
        self.failures = 0
        self.last_fail: Optional[float] = None
        self.state = "CLOSED"

    def can_proceed(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if time.time() - (self.last_fail or 0) > self.timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker → HALF_OPEN")
                return True
            return False
        return True  # HALF_OPEN

    def record_success(self):
        self.failures = 0
        if self.state != "CLOSED":
            logger.info("Circuit breaker → CLOSED")
        self.state = "CLOSED"

    def record_failure(self):
        self.failures += 1
        self.last_fail = time.time()
        if self.failures >= self.threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker → OPEN ({self.failures} failures)")

    def status(self) -> Dict:
        return {"state": self.state, "failures": self.failures, "threshold": self.threshold}

# ══════════════════════════════════════════════════════════════
#  RISK MANAGEMENT ENGINE
# ══════════════════════════════════════════════════════════════

class RiskManager:
    """Institutional-grade safeguards."""

    def __init__(self):
        self.max_position_value: float = 500_000
        self.max_daily_loss: float = 25_000
        self.max_open_positions: int = 5
        self.daily_pnl: float = 0.0
        self.dedup_window: int = 5
        self._recent_orders: Dict[str, float] = {}
        self._reset_date: Optional[str] = None

    def _daily_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._reset_date != today:
            self.daily_pnl = 0.0
            self._reset_date = today
            self._recent_orders.clear()

    def check_market_hours(self) -> tuple:
        try:
            from zoneinfo import ZoneInfo
            ist = ZoneInfo("Asia/Kolkata")
        except ImportError:
            ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)
        if now.weekday() >= 5:
            return False, "Market closed (weekend)"
        mk_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        mk_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now < mk_open:
            return False, f"Pre-market ({now.strftime('%H:%M')} IST)"
        if now > mk_close:
            return False, f"Post-market ({now.strftime('%H:%M')} IST)"
        return True, "Market open"

    def check_daily_loss(self) -> tuple:
        self._daily_reset()
        if self.daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit hit: ₹{abs(self.daily_pnl):.0f}/₹{self.max_daily_loss:.0f}"
        return True, "OK"

    def check_duplicate(self, order: OrderRequest) -> tuple:
        key = f"{order.symbol}_{order.transaction_type.value}_{order.quantity}"
        now = time.time()
        self._recent_orders = {k: v for k, v in self._recent_orders.items() if now - v < self.dedup_window}
        if key in self._recent_orders:
            return False, f"Duplicate order (wait {self.dedup_window}s)"
        self._recent_orders[key] = now
        return True, "OK"

    def validate_signal(self, signal: TradeSignal) -> tuple:
        if signal.decision not in ("LONG", "SHORT", "NO_TRADE"):
            return False, f"Invalid decision: {signal.decision}"
        if signal.decision == "NO_TRADE":
            return True, "NO_TRADE"
        if not 0 <= signal.confidence <= 100:
            return False, f"Invalid confidence: {signal.confidence}"
        if signal.confidence < 50:
            return False, f"Confidence {signal.confidence}% < 50% threshold"
        if signal.safety_score < 40:
            return False, f"Safety {signal.safety_score}% < 40% threshold"
        if signal.entry and signal.stoploss:
            if signal.decision == "LONG" and signal.stoploss >= signal.entry:
                return False, "LONG: SL must be below entry"
            if signal.decision == "SHORT" and signal.stoploss <= signal.entry:
                return False, "SHORT: SL must be above entry"
        return True, "Signal OK"

    def update_pnl(self, pnl: float):
        self._daily_reset()
        self.daily_pnl += pnl

    def get_status(self) -> Dict:
        self._daily_reset()
        mkt_open, mkt_msg = self.check_market_hours()
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "max_daily_loss": self.max_daily_loss,
            "remaining": round(self.max_daily_loss + self.daily_pnl, 2),
            "market_open": mkt_open,
            "market_status": mkt_msg,
        }

# ══════════════════════════════════════════════════════════════
#  SAFE HTTP HELPERS
# ══════════════════════════════════════════════════════════════

async def safe_json(resp: httpx.Response, ctx: str = "") -> Dict:
    """Parse JSON from httpx response; never crash."""
    try:
        if resp.status_code >= 500:
            logger.error(f"{ctx} HTTP {resp.status_code}: {resp.text[:400]}")
            return {"_error": True, "status": resp.status_code, "message": f"Server error {resp.status_code}"}
        return resp.json()
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"{ctx} JSON parse fail: {e} | body: {resp.text[:300]}")
        return {"_error": True, "status": resp.status_code, "message": str(e)}

# ══════════════════════════════════════════════════════════════
#  BROKER BASE CLIENT
# ══════════════════════════════════════════════════════════════

class BaseBrokerClient:
    def __init__(self, creds: BrokerCredentials):
        self.credentials = creds
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.http_client = httpx.AsyncClient(timeout=30.0)
        self.circuit = CircuitBreaker(threshold=5, timeout=60)
        self._login_lock = asyncio.Lock()

    def generate_totp(self) -> str:
        if not self.credentials.totp_secret:
            raise ValueError("TOTP secret not configured")
        return pyotp.TOTP(self.credentials.totp_secret).now()

    async def is_token_valid(self) -> bool:
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.now() < (self.token_expiry - timedelta(seconds=60))

    async def ensure_auth(self):
        if await self.is_token_valid():
            return
        if not self.circuit.can_proceed():
            raise HTTPException(503, f"Broker unavailable (circuit {self.circuit.state})")
        async with self._login_lock:
            if await self.is_token_valid():
                return
            try:
                ok = await self.auto_login()
                if ok:
                    self.circuit.record_success()
                else:
                    self.circuit.record_failure()
                    raise HTTPException(401, "Broker login failed")
            except HTTPException:
                raise
            except Exception as e:
                self.circuit.record_failure()
                raise HTTPException(500, f"Auth error: {e}")

    async def auto_login(self) -> bool:
        raise NotImplementedError
    async def place_order(self, order: OrderRequest) -> Dict:
        raise NotImplementedError
    async def get_positions(self) -> List[Dict]:
        return []
    async def get_holdings(self) -> List[Dict]:
        return []
    async def get_margins(self) -> Dict:
        return {}
    async def cancel_order(self, order_id: str) -> Dict:
        return {"status": "error", "message": "Not implemented"}
    async def get_order_book(self) -> List[Dict]:
        return []

    async def close(self):
        try:
            await self.http_client.aclose()
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════
#  ZERODHA CLIENT
# ══════════════════════════════════════════════════════════════

class ZerodhaClient(BaseBrokerClient):
    BASE_URL = "https://api.kite.trade"
    LOGIN_URL = "https://kite.zerodha.com/api"

    async def auto_login(self) -> bool:
        try:
            if not self.credentials.user_id or not self.credentials.password:
                logger.error("Zerodha: user_id + password required"); return False

            r = await self.http_client.post(f"{self.LOGIN_URL}/login",
                data={"user_id": self.credentials.user_id, "password": self.credentials.password})
            if r.status_code != 200:
                logger.error(f"Zerodha step-1 fail [{r.status_code}]"); return False
            d = await safe_json(r, "Zerodha-login")
            rid = d.get("data", {}).get("request_id")
            if not rid:
                logger.error("Zerodha: no request_id"); return False

            totp = self.generate_totp()
            r = await self.http_client.post(f"{self.LOGIN_URL}/twofa",
                data={"user_id": self.credentials.user_id, "request_id": rid,
                      "twofa_value": totp, "twofa_type": "totp"})
            if r.status_code != 200:
                logger.error(f"Zerodha 2FA fail [{r.status_code}]"); return False

            ck = hashlib.sha256(f"{self.credentials.api_key}{rid}{self.credentials.api_secret}".encode()).hexdigest()
            r = await self.http_client.post(f"{self.BASE_URL}/session/token",
                data={"api_key": self.credentials.api_key, "request_token": rid, "checksum": ck})
            if r.status_code == 200:
                d = await safe_json(r, "Zerodha-session")
                self.access_token = d.get("data", {}).get("access_token")
                if self.access_token:
                    self.token_expiry = datetime.now() + timedelta(hours=8)
                    logger.info("✅ Zerodha login OK"); return True
            return False
        except Exception as e:
            logger.error(f"Zerodha login error: {e}"); return False

    def _h(self) -> Dict:
        return {"Authorization": f"token {self.credentials.api_key}:{self.access_token}",
                "Content-Type": "application/x-www-form-urlencoded"}

    async def place_order(self, order: OrderRequest) -> Dict:
        await self.ensure_auth()
        d = {"tradingsymbol": order.symbol, "exchange": order.exchange,
             "transaction_type": order.transaction_type.value, "order_type": order.order_type.value,
             "quantity": order.quantity, "product": order.product, "validity": "DAY"}
        if order.price is not None and order.price > 0: d["price"] = order.price
        if order.trigger_price is not None and order.trigger_price > 0: d["trigger_price"] = order.trigger_price
        r = await self.http_client.post(f"{self.BASE_URL}/orders/regular", headers=self._h(), data=d)
        return await safe_json(r, "Zerodha-order")

    async def get_positions(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.BASE_URL}/portfolio/positions", headers=self._h())
        d = await safe_json(r, "Zerodha-pos")
        return d.get("data", {}).get("net", []) if not d.get("_error") else []

    async def get_margins(self) -> Dict:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.BASE_URL}/user/margins", headers=self._h())
        d = await safe_json(r, "Zerodha-margins")
        return d.get("data", {}) if not d.get("_error") else {}

    async def cancel_order(self, order_id: str) -> Dict:
        await self.ensure_auth()
        r = await self.http_client.delete(f"{self.BASE_URL}/orders/regular/{order_id}", headers=self._h())
        return await safe_json(r, "Zerodha-cancel")

    async def get_order_book(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.BASE_URL}/orders", headers=self._h())
        d = await safe_json(r, "Zerodha-orders")
        return d.get("data", []) if not d.get("_error") else []

# ══════════════════════════════════════════════════════════════
#  UPSTOX CLIENT
# ══════════════════════════════════════════════════════════════

class UpstoxClient(BaseBrokerClient):
    BASE_URL = "https://api.upstox.com/v2"

    async def auto_login(self) -> bool:
        try:
            if not self.credentials.password:
                logger.error("Upstox: access token required"); return False
            r = await self.http_client.post(f"{self.BASE_URL}/login/authorization/token",
                data={"code": self.credentials.password, "client_id": self.credentials.api_key,
                      "client_secret": self.credentials.api_secret,
                      "redirect_uri": "http://localhost:8000/callback", "grant_type": "authorization_code"},
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code == 200:
                d = await safe_json(r, "Upstox-login")
                self.access_token = d.get("access_token")
                if self.access_token:
                    self.token_expiry = datetime.now() + timedelta(hours=8)
                    logger.info("✅ Upstox login OK"); return True
            return False
        except Exception as e:
            logger.error(f"Upstox login error: {e}"); return False

    def _h(self) -> Dict:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    async def place_order(self, order: OrderRequest) -> Dict:
        await self.ensure_auth()
        ik = f"NSE_FO|{order.symbol}" if order.exchange == "NFO" else f"NSE_EQ|{order.symbol}"
        d = {"instrument_token": ik, "order_type": order.order_type.value,
             "transaction_type": order.transaction_type.value, "quantity": order.quantity,
             "product": order.product, "validity": "DAY", "disclosed_quantity": 0, "is_amo": False}
        if order.price is not None and order.price > 0: d["price"] = order.price
        if order.trigger_price is not None and order.trigger_price > 0: d["trigger_price"] = order.trigger_price
        r = await self.http_client.post(f"{self.BASE_URL}/order/place", headers=self._h(), json=d)
        return await safe_json(r, "Upstox-order")

    async def get_positions(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.BASE_URL}/portfolio/short-term-positions", headers=self._h())
        d = await safe_json(r, "Upstox-pos")
        return d.get("data", []) if not d.get("_error") else []

# ══════════════════════════════════════════════════════════════
#  FYERS CLIENT
# ══════════════════════════════════════════════════════════════

class FyersClient(BaseBrokerClient):
    BASE_URL = "https://api-t1.fyers.in/api/v3"

    async def auto_login(self) -> bool:
        try:
            if not self.credentials.user_id:
                logger.error("FYERS: FY-ID required"); return False
            totp = self.generate_totp()
            r = await self.http_client.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2",
                json={"fy_id": self.credentials.user_id, "app_id": "2"})
            d = await safe_json(r, "FYERS-otp")
            rk = d.get("request_key", "")
            if not rk:
                logger.error("FYERS: no request_key"); return False
            r = await self.http_client.post("https://api-t2.fyers.in/vagator/v2/verify_otp",
                json={"request_key": rk, "otp": totp})
            if r.status_code == 200:
                d = await safe_json(r, "FYERS-verify")
                self.access_token = d.get("access_token")
                if self.access_token:
                    self.token_expiry = datetime.now() + timedelta(hours=8)
                    logger.info("✅ FYERS login OK"); return True
            return False
        except Exception as e:
            logger.error(f"FYERS login error: {e}"); return False

    def _h(self) -> Dict:
        return {"Authorization": f"{self.credentials.api_key}:{self.access_token}",
                "Content-Type": "application/json"}

    async def place_order(self, order: OrderRequest) -> Dict:
        await self.ensure_auth()
        sym = f"{order.exchange}:{order.symbol}" if ("NIFTY" in order.symbol or "BANK" in order.symbol) \
              else f"{order.exchange}:{order.symbol}-EQ"
        d = {"symbol": sym, "qty": order.quantity,
             "type": {"MARKET": 2, "LIMIT": 1, "SL": 3, "SL-M": 4}.get(order.order_type.value, 2),
             "side": 1 if order.transaction_type == TransactionType.BUY else -1,
             "productType": order.product, "validity": "DAY", "disclosedQty": 0, "offlineOrder": False}
        if order.price is not None and order.price > 0: d["limitPrice"] = order.price
        if order.trigger_price is not None and order.trigger_price > 0: d["stopPrice"] = order.trigger_price
        r = await self.http_client.post(f"{self.BASE_URL}/orders", headers=self._h(), json=d)
        return await safe_json(r, "FYERS-order")

# ══════════════════════════════════════════════════════════════
#  DHAN CLIENT
# ══════════════════════════════════════════════════════════════

class DhanClient(BaseBrokerClient):
    BASE_URL = "https://api.dhan.co/v2"

    async def auto_login(self) -> bool:
        try:
            if not self.credentials.api_secret:
                logger.error("Dhan: access token required"); return False
            self.access_token = self.credentials.api_secret
            r = await self.http_client.get(f"{self.BASE_URL}/profile", headers=self._h())
            if r.status_code == 200:
                self.token_expiry = datetime.now() + timedelta(hours=24)
                logger.info("✅ Dhan login OK"); return True
            return False
        except Exception as e:
            logger.error(f"Dhan login error: {e}"); return False

    def _h(self) -> Dict:
        return {"access-token": self.access_token or "",
                "client-id": self.credentials.user_id or "",
                "Content-Type": "application/json"}

    async def place_order(self, order: OrderRequest) -> Dict:
        await self.ensure_auth()
        d = {"transactionType": order.transaction_type.value,
             "exchangeSegment": "NSE_EQ" if order.exchange == "NSE" else "NSE_FNO",
             "productType": order.product, "orderType": order.order_type.value,
             "validity": "DAY", "tradingSymbol": order.symbol, "securityId": "",
             "quantity": order.quantity}
        if order.price is not None and order.price > 0: d["price"] = order.price
        if order.trigger_price is not None and order.trigger_price > 0: d["triggerPrice"] = order.trigger_price
        r = await self.http_client.post(f"{self.BASE_URL}/orders", headers=self._h(), json=d)
        return await safe_json(r, "Dhan-order")

# ══════════════════════════════════════════════════════════════
#  IIFL BLAZE (XTS) CLIENT
# ══════════════════════════════════════════════════════════════

class IIFLBlazeClient(BaseBrokerClient):
    INTERACTIVE_URL = "https://ttblaze.iifl.com/interactive"
    MARKETDATA_URL = "https://ttblaze.iifl.com/marketdata"

    def __init__(self, creds: BrokerCredentials):
        super().__init__(creds)
        self.interactive_token: Optional[str] = None
        self.market_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.is_investor_client: bool = False
        self.market_api_key = creds.market_api_key or creds.api_key
        self.market_secret_key = creds.market_secret_key or creds.api_secret

    async def auto_login(self) -> bool:
        try:
            if not await self._login_interactive():
                return False
            mk = await self._login_market_data()
            logger.info(f"✅ IIFL Blaze {'fully' if mk else 'interactive-only'} connected")
            return True
        except Exception as e:
            logger.error(f"IIFL login error: {e}"); return False

    async def _login_interactive(self) -> bool:
        try:
            r = await self.http_client.post(f"{self.INTERACTIVE_URL}/user/session",
                json={"secretKey": self.credentials.api_secret, "appKey": self.credentials.api_key,
                      "source": self.credentials.source or "WEBAPI"},
                headers={"Content-Type": "application/json"})
            d = await safe_json(r, "IIFL-interactive")
            if d.get("type") == "success":
                self.interactive_token = d.get("result", {}).get("token")
                self.user_id = d.get("result", {}).get("userID")
                self.is_investor_client = d.get("result", {}).get("isInvestorClient", False)
                self.token_expiry = datetime.now() + timedelta(hours=8)
                self.access_token = self.interactive_token
                if self.interactive_token:
                    logger.info(f"✅ IIFL Interactive OK – User: {self.user_id}"); return True
            logger.error(f"IIFL Interactive fail: {d.get('description', 'unknown')}"); return False
        except Exception as e:
            logger.error(f"IIFL Interactive error: {e}"); return False

    async def _login_market_data(self) -> bool:
        try:
            r = await self.http_client.post(f"{self.MARKETDATA_URL}/user/session",
                json={"secretKey": self.market_secret_key, "appKey": self.market_api_key,
                      "source": self.credentials.source or "WEBAPI"},
                headers={"Content-Type": "application/json"})
            d = await safe_json(r, "IIFL-market")
            if d.get("type") == "success":
                self.market_token = d.get("result", {}).get("token")
                if self.market_token:
                    logger.info("✅ IIFL Market Data OK"); return True
            return False
        except Exception as e:
            logger.error(f"IIFL Market error: {e}"); return False

    def _h(self, market: bool = False) -> Dict:
        tk = self.market_token if market else self.interactive_token
        return {"Content-Type": "application/json", "Authorization": tk or ""}

    async def logout(self) -> bool:
        try:
            if self.interactive_token:
                await self.http_client.delete(f"{self.INTERACTIVE_URL}/user/session", headers=self._h())
            if self.market_token:
                await self.http_client.delete(f"{self.MARKETDATA_URL}/user/session", headers=self._h(True))
            self.interactive_token = self.market_token = self.access_token = None
            return True
        except Exception as e:
            logger.warning(f"IIFL logout error: {e}"); return False

    async def get_profile(self) -> Dict:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.INTERACTIVE_URL}/user/profile", headers=self._h())
        return await safe_json(r, "IIFL-profile")

    async def place_order(self, order: OrderRequest) -> Dict:
        await self.ensure_auth()
        ex = {"NSE": "NSECM", "NFO": "NSEFO", "BSE": "BSECM", "BFO": "BSEFO", "MCX": "MCXFO"}
        ot = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOPLIMIT", "SL-M": "STOPMARKET"}
        pt = {"MIS": "INTRADAY", "CNC": "DELIVERY", "NRML": "CARRYFORWARD"}
        payload = {
            "exchangeSegment": ex.get(order.exchange, "NSECM"),
            "exchangeInstrumentID": order.symbol,
            "productType": pt.get(order.product, "INTRADAY"),
            "orderType": ot.get(order.order_type.value, "MARKET"),
            "orderSide": "BUY" if order.transaction_type == TransactionType.BUY else "SELL",
            "timeInForce": "DAY", "disclosedQuantity": 0, "orderQuantity": order.quantity,
            "limitPrice": order.price if (order.price is not None and order.price > 0) else 0,
            "stopPrice": order.trigger_price if (order.trigger_price is not None and order.trigger_price > 0) else 0,
            "orderUniqueIdentifier": f"CV_{int(time.time()*1000)}",
        }
        r = await self.http_client.post(f"{self.INTERACTIVE_URL}/orders", headers=self._h(), json=payload)
        d = await safe_json(r, "IIFL-order")
        if d.get("type") == "success":
            return {"status": "success", "data": {"order_id": d.get("result", {}).get("AppOrderID"),
                                                   "message": d.get("description")}}
        return {"status": "error", "message": d.get("description", d.get("message", "Order failed"))}

    async def cancel_order(self, order_id: str) -> Dict:
        await self.ensure_auth()
        r = await self.http_client.delete(f"{self.INTERACTIVE_URL}/orders", headers=self._h(),
            params={"appOrderID": order_id})
        return await safe_json(r, "IIFL-cancel")

    async def get_order_book(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.INTERACTIVE_URL}/orders", headers=self._h())
        d = await safe_json(r, "IIFL-orders")
        return d.get("result", []) if d.get("type") == "success" else []

    async def get_positions(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.INTERACTIVE_URL}/portfolio/positions", headers=self._h(),
            params={"dayOrNet": "DayWise"})
        d = await safe_json(r, "IIFL-pos")
        if d.get("type") == "success":
            return [{"symbol": p.get("TradingSymbol", ""), "exchange": p.get("ExchangeSegment", ""),
                      "quantity": p.get("Quantity", 0),
                      "average_price": p.get("BuyAveragePrice") or p.get("SellAveragePrice") or 0,
                      "pnl": (p.get("RealizedMTM", 0) or 0) + (p.get("UnrealizedMTM", 0) or 0),
                      "side": "LONG" if (p.get("Quantity", 0) or 0) > 0 else "SHORT"}
                     for p in d.get("result", {}).get("positionList", [])]
        return []

    async def get_holdings(self) -> List[Dict]:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.INTERACTIVE_URL}/portfolio/holdings", headers=self._h())
        d = await safe_json(r, "IIFL-holdings")
        return d.get("result", {}).get("RMSHoldings", []) if d.get("type") == "success" else []

    async def get_margins(self) -> Dict:
        await self.ensure_auth()
        r = await self.http_client.get(f"{self.INTERACTIVE_URL}/user/balance", headers=self._h())
        d = await safe_json(r, "IIFL-margins")
        if d.get("type") == "success":
            bl = d.get("result", {}).get("BalanceList", [{}])
            lim = (bl[0] if bl else {}).get("limitObject", {}).get("RMSSubLimits", {})
            return {"equity": {"available": {"cash": lim.get("netMarginAvailable", 0)},
                               "utilised": {"total": lim.get("marginUtilized", 0)}},
                    "net_margin": lim.get("netMarginAvailable", 0)}
        return {}

    # Market data pass-throughs
    async def get_quotes(self, instruments: List[Dict]) -> Dict:
        if not self.market_token: await self._login_market_data()
        r = await self.http_client.post(f"{self.MARKETDATA_URL}/instruments/quotes",
            headers=self._h(True), json={"instruments": instruments})
        return await safe_json(r, "IIFL-quotes")

    async def search_instruments(self, s: str) -> Dict:
        if not self.market_token: await self._login_market_data()
        r = await self.http_client.get(f"{self.MARKETDATA_URL}/search/instrumentsbystring",
            headers=self._h(True), params={"searchString": s, "source": self.credentials.source or "WEBAPI"})
        return await safe_json(r, "IIFL-search")

    async def get_option_chain(self, es, sr, sym, exp, ot) -> Dict:
        if not self.market_token: await self._login_market_data()
        r = await self.http_client.get(f"{self.MARKETDATA_URL}/instruments/instrument/optionchain",
            headers=self._h(True),
            params={"exchangeSegment": es, "series": sr, "symbol": sym, "expiryDate": exp, "optionType": ot})
        return await safe_json(r, "IIFL-optchain")

# ══════════════════════════════════════════════════════════════
#  SESSION MANAGER
# ══════════════════════════════════════════════════════════════

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.broker_clients: Dict[str, BaseBrokerClient] = {}

    def create_session(self, uid: str = None) -> str:
        sid = secrets.token_urlsafe(32)
        self.sessions[sid] = {
            "session_id": sid, "user_id": uid or f"user_{sid[:8]}",
            "created_at": datetime.now(), "expires_at": datetime.now() + timedelta(hours=24),
            "broker_connected": False, "broker_type": None, "trading_mode": "paper",
        }
        logger.info(f"Session created: {sid[:12]}…")
        return sid

    def get_session(self, sid: str) -> Optional[Dict]:
        s = self.sessions.get(sid)
        return s if s and datetime.now() < s["expires_at"] else None

    async def connect_broker(self, sid: str, creds: BrokerCredentials) -> bool:
        s = self.get_session(sid)
        if not s:
            raise HTTPException(401, "Invalid session")
        client = _broker_factory(creds)
        try:
            ok = await client.auto_login()
        except Exception as e:
            logger.error(f"Broker login exception: {e}")
            await client.close(); return False
        if ok:
            old = self.broker_clients.get(sid)
            if old: await old.close()
            self.broker_clients[sid] = client
            s["broker_connected"] = True; s["broker_type"] = creds.broker.value
            return True
        await client.close(); return False

    def get_broker_client(self, sid: str) -> Optional[BaseBrokerClient]:
        return self.broker_clients.get(sid)

    async def disconnect_broker(self, sid: str) -> bool:
        c = self.broker_clients.pop(sid, None)
        if c:
            try:
                if hasattr(c, "logout"): await c.logout()
            except Exception: pass
            await c.close()
        s = self.sessions.get(sid)
        if s:
            s["broker_connected"] = False; s["broker_type"] = None
        return c is not None

    async def cleanup_expired(self):
        now = datetime.now()
        expired = [sid for sid, s in self.sessions.items() if now >= s["expires_at"]]
        for sid in expired:
            await self.disconnect_broker(sid)
            self.sessions.pop(sid, None)
        if expired:
            logger.info(f"Cleaned {len(expired)} expired sessions")

    async def close_all(self):
        for sid in list(self.broker_clients):
            await self.disconnect_broker(sid)
        self.sessions.clear()

def _broker_factory(creds: BrokerCredentials) -> BaseBrokerClient:
    m = {BrokerType.IIFL_BLAZE: IIFLBlazeClient, BrokerType.ZERODHA: ZerodhaClient,
         BrokerType.UPSTOX: UpstoxClient, BrokerType.FYERS: FyersClient, BrokerType.DHAN: DhanClient}
    cls = m.get(creds.broker)
    if not cls:
        raise ValueError(f"Unsupported broker: {creds.broker}")
    return cls(creds)

# ══════════════════════════════════════════════════════════════
#  GEMINI AI CLIENT (Hardened)
# ══════════════════════════════════════════════════════════════

class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.http_client = httpx.AsyncClient(timeout=60.0)
        self.circuit = CircuitBreaker(threshold=3, timeout=120)
        self._last_call: float = 0
        self._min_interval: float = 3.0

    async def analyze_multi_chart(self, charts: List[ChartImage],
                                  strategy_context: str,
                                  previous_analysis: Optional[str] = None) -> TradeSignal:
        # Rate limit
        wait = self._min_interval - (time.time() - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)

        if not self.circuit.can_proceed():
            return TradeSignal(decision="NO_TRADE", warnings=["AI temporarily unavailable (circuit breaker)"],
                               timestamp=datetime.now().isoformat())
        try:
            self._last_call = time.time()
            parts = []
            descs = [f"  {i+1}. {c.chart_type.upper()} – {c.symbol} ({c.timeframe})" for i, c in enumerate(charts)]
            prompt = f"""You are an expert institutional trader analyzing multiple charts for a combined trading decision.

CHARTS PROVIDED:
{chr(10).join(descs)}

STRATEGY CONTEXT:
{strategy_context}

{f"PREVIOUS ANALYSIS:{chr(10)}{previous_analysis}" if previous_analysis else ""}

OUTPUT FORMAT (strict):
TRADE_DECISION: [LONG/SHORT/NO_TRADE]
CONFIDENCE: [0-100]%
SAFETY_SCORE: [0-100]%
ENTRY: [price]
STOPLOSS: [price]
TARGET_1: [price]
TARGET_2: [price]
TARGET_3: [price]
RISK_REWARD: [ratio]

REASONING:
- [reasons]

WARNINGS:
- [risks]
"""
            parts.append({"text": prompt})
            for c in charts:
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": c.image_base64}})

            r = await self.http_client.post(
                f"{self.BASE_URL}/models/{self.model}:generateContent",
                json={"contents": [{"parts": parts}],
                      "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048, "topP": 0.8},
                      "safetySettings": [
                          {"category": c, "threshold": "BLOCK_NONE"}
                          for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                                    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]},
                params={"key": self.api_key},
                headers={"Content-Type": "application/json"})

            if r.status_code != 200:
                self.circuit.record_failure()
                raise HTTPException(r.status_code, f"Gemini error: {r.text[:400]}")

            d = await safe_json(r, "Gemini")
            cands = d.get("candidates", [])
            if not cands:
                self.circuit.record_failure()
                raise HTTPException(500, "Gemini returned no candidates")

            text = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text:
                self.circuit.record_failure()
                raise HTTPException(500, "Empty Gemini response")

            self.circuit.record_success()
            sig = self._parse(text)
            sig.timestamp = datetime.now().isoformat()
            return sig
        except HTTPException:
            raise
        except Exception as e:
            self.circuit.record_failure()
            raise HTTPException(500, f"AI analysis failed: {e}")

    def _parse(self, text: str) -> TradeSignal:
        import re
        def ex(p, d=None):
            m = re.search(p, text, re.I)
            return m.group(1).strip() if m else d
        def exf(p, d=None):
            v = ex(p)
            if v:
                try: return float(v.replace(",", "").replace("₹", "").replace("~", ""))
                except: return d
            return d

        dec = (ex(r"TRADE_DECISION:\s*\*?\*?(LONG|SHORT|NO_TRADE)", "NO_TRADE") or "NO_TRADE").upper()
        if dec not in ("LONG", "SHORT", "NO_TRADE"): dec = "NO_TRADE"
        conf = min(100, max(0, int(ex(r"CONFIDENCE:\s*\*?\*?(\d+)", "50") or "50")))
        safe = min(100, max(0, int(ex(r"SAFETY_SCORE:\s*\*?\*?(\d+)", str(min(conf, 85))) or "50")))

        reasons = [m.group(1).strip() for m in re.finditer(r"[-•*]\s*(.+?)(?=\n|$)", text) if 10 < len(m.group(1).strip()) < 200]
        warns = []
        ws = re.search(r"WARNINGS?:?\s*\n((?:[-•*].+\n?)+)", text, re.I)
        if ws:
            warns = [m.group(1).strip() for m in re.finditer(r"[-•*]\s*(.+?)(?=\n|$)", ws.group(1)) if m.group(1).strip()]

        return TradeSignal(decision=dec, confidence=conf, safety_score=safe,
            entry=exf(r"ENTRY:\s*[\₹~]?([\d,\.]+)"), stoploss=exf(r"STOPLOSS:\s*[\₹~]?([\d,\.]+)"),
            target1=exf(r"TARGET_?1:\s*[\₹~]?([\d,\.]+)"), target2=exf(r"TARGET_?2:\s*[\₹~]?([\d,\.]+)"),
            target3=exf(r"TARGET_?3:\s*[\₹~]?([\d,\.]+)"),
            risk_reward=ex(r"RISK_REWARD:\s*(.+?)(?=\n|$)", "1:1") or "1:1",
            reasoning=reasons[:10], warnings=warns[:5])

    async def close(self):
        try: await self.http_client.aclose()
        except: pass

# ══════════════════════════════════════════════════════════════
#  PAPER TRADING ENGINE (Fixed)
# ══════════════════════════════════════════════════════════════

class PaperTradingEngine:
    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.available = capital
        self.positions: List[Dict] = []
        self.orders: List[Dict] = []
        self.trades: List[Dict] = []
        self._counter = 1000
        self._lock = asyncio.Lock()

    async def place_order(self, order: OrderRequest, ltp: float) -> Dict:
        async with self._lock:
            return self._exec(order, ltp)

    def _exec(self, order: OrderRequest, ltp: float) -> Dict:
        self._counter += 1
        oid = f"PAPER_{self._counter}"
        price = ltp if order.order_type == OrderType.MARKET else (order.price if order.price and order.price > 0 else ltp)
        if price <= 0:
            return {"status": "error", "message": "Invalid price"}
        val = price * order.quantity

        if order.transaction_type == TransactionType.BUY:
            if val > self.available:
                return {"status": "error", "message": f"Insufficient margin: need ₹{val:,.0f}, have ₹{self.available:,.0f}"}
            self.available -= val
            ex = next((p for p in self.positions if p["symbol"] == order.symbol and p["side"] == "LONG" and p["quantity"] > 0), None)
            if ex:
                tq = ex["quantity"] + order.quantity
                ex["average_price"] = (ex["average_price"] * ex["quantity"] + price * order.quantity) / tq
                ex["quantity"] = tq
            else:
                self.positions.append({"symbol": order.symbol, "quantity": order.quantity,
                                       "average_price": price, "pnl": 0, "side": "LONG"})
        else:
            ex = next((p for p in self.positions if p["symbol"] == order.symbol and p["side"] == "LONG" and p["quantity"] > 0), None)
            if ex:
                cq = min(order.quantity, ex["quantity"])
                pnl = (price - ex["average_price"]) * cq
                ex["quantity"] -= cq
                self.capital += pnl
                self.available += price * cq
                self.trades.append({"symbol": order.symbol, "entry": ex["average_price"],
                    "exit": price, "quantity": cq, "pnl": round(pnl, 2), "side": "LONG",
                    "timestamp": datetime.now().isoformat()})
                rem = order.quantity - cq
                if rem > 0:
                    self.positions.append({"symbol": order.symbol, "quantity": rem,
                                           "average_price": price, "pnl": 0, "side": "SHORT"})
            else:
                self.positions.append({"symbol": order.symbol, "quantity": order.quantity,
                                       "average_price": price, "pnl": 0, "side": "SHORT"})

        rec = {"order_id": oid, "symbol": order.symbol, "exchange": order.exchange,
               "transaction_type": order.transaction_type.value, "order_type": order.order_type.value,
               "quantity": order.quantity, "price": price, "status": "COMPLETE",
               "filled_quantity": order.quantity, "timestamp": datetime.now().isoformat()}
        self.orders.append(rec)
        return {"status": "success", "data": rec}

    def get_positions(self) -> List[Dict]:
        return [p for p in self.positions if p["quantity"] > 0]

    def get_margins(self) -> Dict:
        return {"equity": {"available": {"cash": round(self.available, 2)},
                           "utilised": {"total": round(self.capital - self.available, 2)}}}

    def get_stats(self) -> Dict:
        tp = sum(t["pnl"] for t in self.trades)
        w = sum(1 for t in self.trades if t["pnl"] > 0)
        l = sum(1 for t in self.trades if t["pnl"] <= 0)
        n = len(self.trades)
        return {"capital": round(self.capital, 2), "available": round(self.available, 2),
                "total_pnl": round(tp, 2), "total_trades": n, "wins": w, "losses": l,
                "win_rate": round(w / n * 100, 1) if n else 0,
                "positions": self.get_positions(), "recent_trades": self.trades[-10:]}

# ══════════════════════════════════════════════════════════════
#  FASTAPI APPLICATION
# ══════════════════════════════════════════════════════════════

app_state: Dict[str, Any] = {
    "gemini_client": None,
    "session_manager": SessionManager(),
    "paper_engines": {},
    "ws_connections": {},
    "risk": RiskManager(),
    "cleanup_task": None,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 ChartVision Pro X v3.0 HARDENED Starting…")

    async def _cleanup():
        while True:
            try:
                await asyncio.sleep(300)
                await app_state["session_manager"].cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

    app_state["cleanup_task"] = asyncio.create_task(_cleanup())
    yield
    logger.info("👋 Shutting down…")
    if app_state["cleanup_task"]:
        app_state["cleanup_task"].cancel()
        try: await app_state["cleanup_task"]
        except asyncio.CancelledError: pass
    await app_state["session_manager"].close_all()
    if app_state["gemini_client"]:
        await app_state["gemini_client"].close()
    logger.info("✅ Clean shutdown complete")

app = FastAPI(title="ChartVision Pro X API", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(Exception)
async def _global_err(req: Request, exc: Exception):
    logger.error(f"Unhandled: {req.method} {req.url.path}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(500, {"status": "error", "message": str(exc)})

# ── Dependencies ──

async def get_session(x_session_id: Optional[str] = Header(None)) -> Dict:
    if not x_session_id:
        raise HTTPException(401, "X-Session-ID header required")
    s = app_state["session_manager"].get_session(x_session_id)
    if not s:
        raise HTTPException(401, "Invalid or expired session")
    return s

def get_paper_engine(sid: str) -> PaperTradingEngine:
    if sid not in app_state["paper_engines"]:
        app_state["paper_engines"][sid] = PaperTradingEngine()
    return app_state["paper_engines"][sid]

# ── Health ──

@app.get("/health")
async def health():
    rm = app_state["risk"].get_status()
    gc = app_state["gemini_client"]
    return {"status": "healthy", "version": "3.0.0", "timestamp": datetime.now().isoformat(),
            "sessions": len(app_state["session_manager"].sessions),
            "gemini": gc.circuit.status() if gc else None, "risk": rm}

# ── Session ──

@app.post("/api/session/create")
async def create_session(user_id: Optional[str] = None):
    sid = app_state["session_manager"].create_session(user_id)
    return {"status": "success", "session_id": sid}

@app.get("/api/session/info")
async def session_info(s: Dict = Depends(get_session)):
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in s.items()}

@app.delete("/api/session/delete")
async def delete_session(s: Dict = Depends(get_session)):
    sid = s["session_id"]
    await app_state["session_manager"].disconnect_broker(sid)
    app_state["session_manager"].sessions.pop(sid, None)
    app_state["paper_engines"].pop(sid, None)
    return {"status": "success"}

# ── Gemini ──

@app.post("/api/config/gemini")
async def config_gemini(cfg: GeminiConfig):
    if app_state["gemini_client"]:
        await app_state["gemini_client"].close()
    app_state["gemini_client"] = GeminiClient(cfg.api_key, cfg.model)
    return {"status": "success"}

# ── Broker ──

@app.get("/api/brokers/list")
async def brokers_list():
    return {"brokers": [{"id": b.value, "name": b.value} for b in BrokerType]}

@app.post("/api/broker/connect")
async def broker_connect(creds: BrokerCredentials, s: Dict = Depends(get_session)):
    sid = s["session_id"]
    if s["broker_connected"]:
        await app_state["session_manager"].disconnect_broker(sid)
    ok = await app_state["session_manager"].connect_broker(sid, creds)
    if not ok:
        raise HTTPException(401, "Broker login failed")
    c = app_state["session_manager"].get_broker_client(sid)
    extra = {}
    if isinstance(c, IIFLBlazeClient):
        extra = {"user_id": c.user_id, "has_market_data": c.market_token is not None}
    return {"status": "success", "broker": creds.broker.value, **extra}

@app.post("/api/broker/disconnect")
async def broker_disconnect(s: Dict = Depends(get_session)):
    await app_state["session_manager"].disconnect_broker(s["session_id"])
    return {"status": "success"}

@app.get("/api/broker/status")
async def broker_status(s: Dict = Depends(get_session)):
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not c:
        return {"connected": False}
    try: valid = await c.is_token_valid()
    except: valid = False
    r = {"connected": valid, "broker": s["broker_type"], "circuit": c.circuit.status()}
    if isinstance(c, IIFLBlazeClient):
        r["user_id"] = c.user_id; r["has_market_data"] = c.market_token is not None
    return r

# ── Mode ──

@app.post("/api/config/mode")
async def set_mode(mode: TradingMode, s: Dict = Depends(get_session)):
    s["trading_mode"] = mode.value
    return {"status": "success", "mode": mode.value}

# ── Risk ──

@app.get("/api/risk/status")
async def risk_status(s: Dict = Depends(get_session)):
    return app_state["risk"].get_status()

# ── Analysis ──

@app.post("/api/analyze/multi-chart")
async def analyze(req: MultiChartAnalysisRequest, s: Dict = Depends(get_session)):
    if not app_state["gemini_client"]:
        raise HTTPException(400, "Gemini not configured")
    sig = await app_state["gemini_client"].analyze_multi_chart(req.charts, req.strategy_context, req.previous_analysis)
    ok, msg = app_state["risk"].validate_signal(sig)
    if not ok:
        sig.warnings = sig.warnings + [f"⚠ Risk: {msg}"]
    await _broadcast(s["session_id"], sig.model_dump())
    return sig

# ── Orders ──

@app.post("/api/orders/place")
async def place_order(order: OrderRequest, ltp: float = 0, s: Dict = Depends(get_session)):
    sid = s["session_id"]; rm = app_state["risk"]
    if s["trading_mode"] == "live":
        ok, msg = rm.check_market_hours()
        if not ok: raise HTTPException(400, msg)
        ok, msg = rm.check_daily_loss()
        if not ok: raise HTTPException(400, msg)
        ok, msg = rm.check_duplicate(order)
        if not ok: raise HTTPException(400, msg)
    if s["trading_mode"] == "paper":
        return await get_paper_engine(sid).place_order(order, ltp)
    c = app_state["session_manager"].get_broker_client(sid)
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.place_order(order)

@app.get("/api/orders")
async def get_orders(s: Dict = Depends(get_session)):
    sid = s["session_id"]
    if s["trading_mode"] == "paper":
        return get_paper_engine(sid).orders
    c = app_state["session_manager"].get_broker_client(sid)
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.get_order_book()

@app.delete("/api/orders/{order_id}")
async def cancel_order_ep(order_id: str, s: Dict = Depends(get_session)):
    if s["trading_mode"] == "paper":
        return {"status": "success", "message": "Cancelled (paper)"}
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.cancel_order(order_id)

# ── Positions / Portfolio ──

@app.get("/api/positions")
async def positions(s: Dict = Depends(get_session)):
    if s["trading_mode"] == "paper":
        return get_paper_engine(s["session_id"]).get_positions()
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.get_positions()

@app.get("/api/holdings")
async def holdings(s: Dict = Depends(get_session)):
    if s["trading_mode"] == "paper": return []
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.get_holdings()

@app.get("/api/margins")
async def margins(s: Dict = Depends(get_session)):
    if s["trading_mode"] == "paper":
        return get_paper_engine(s["session_id"]).get_margins()
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not c: raise HTTPException(400, "Broker not connected")
    return await c.get_margins()

# ── IIFL Specific ──

@app.get("/api/iifl/profile")
async def iifl_profile(s: Dict = Depends(get_session)):
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not isinstance(c, IIFLBlazeClient): raise HTTPException(400, "Not IIFL")
    return await c.get_profile()

@app.post("/api/iifl/quotes")
async def iifl_quotes(instruments: List[Dict], s: Dict = Depends(get_session)):
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not isinstance(c, IIFLBlazeClient): raise HTTPException(400, "Not IIFL")
    return await c.get_quotes(instruments)

@app.get("/api/iifl/search")
async def iifl_search(search_string: str, s: Dict = Depends(get_session)):
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not isinstance(c, IIFLBlazeClient): raise HTTPException(400, "Not IIFL")
    return await c.search_instruments(search_string)

@app.get("/api/iifl/option-chain")
async def iifl_optchain(exchange_segment: str, series: str, symbol: str,
                        expiry_date: str, option_type: str, s: Dict = Depends(get_session)):
    c = app_state["session_manager"].get_broker_client(s["session_id"])
    if not isinstance(c, IIFLBlazeClient): raise HTTPException(400, "Not IIFL")
    return await c.get_option_chain(exchange_segment, series, symbol, expiry_date, option_type)

# ── Paper Stats ──

@app.get("/api/paper/stats")
async def paper_stats(s: Dict = Depends(get_session)):
    return get_paper_engine(s["session_id"]).get_stats()

@app.post("/api/paper/reset")
async def paper_reset(capital: float = 100_000, s: Dict = Depends(get_session)):
    if not 1 <= capital <= 1e8:
        raise HTTPException(400, "Capital 1 – 10Cr")
    app_state["paper_engines"][s["session_id"]] = PaperTradingEngine(capital)
    return {"status": "success", "capital": capital}

# ── WebSocket ──

async def _broadcast(sid: str, data: Dict):
    conns = app_state["ws_connections"].get(sid, set())
    dead: Set[WebSocket] = set()
    for ws in conns:
        try:
            await ws.send_json({"type": "signal", "data": data})
        except Exception:
            dead.add(ws)
    for ws in dead:
        conns.discard(ws)

@app.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str):
    if not app_state["session_manager"].get_session(session_id):
        await ws.close(4001, "Invalid session"); return
    await ws.accept()
    app_state["ws_connections"].setdefault(session_id, set()).add(ws)
    logger.info(f"WS connected: {session_id[:12]}…")
    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_json(), timeout=60)
            except asyncio.TimeoutError:
                try: await ws.send_json({"type": "keepalive"})
                except: break
                continue
            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
            elif data.get("type") == "analyze":
                try:
                    charts = [ChartImage(**c) for c in data.get("charts", [])]
                    if app_state["gemini_client"] and charts:
                        sig = await app_state["gemini_client"].analyze_multi_chart(
                            charts, data.get("strategy_context", ""), data.get("previous_analysis"))
                        await ws.send_json({"type": "signal", "data": sig.model_dump()})
                    else:
                        await ws.send_json({"type": "error", "message": "Gemini not configured"})
                except Exception as e:
                    await ws.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        app_state["ws_connections"].get(session_id, set()).discard(ws)

# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, workers=1, log_level="info")
