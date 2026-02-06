import { useState, useRef, useCallback, useEffect } from 'react';

// ==================== CONFIGURATION ====================
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

// ==================== TYPES ====================
const CHART_TYPES = {
  spot: { label: 'Spot Chart', icon: '📈', color: '#39d353', description: 'Price action & trend' },
  market_profile: { label: 'Market Profile', icon: '📊', color: '#58a6ff', description: 'Value area & POC' },
  orderflow: { label: 'Order Flow', icon: '🔥', color: '#f85149', description: 'Delta & imbalances' },
  option_chain: { label: 'Option Chain', icon: '⛓️', color: '#a371f7', description: 'OI & PCR analysis' }
};

const TIMEFRAMES = {
  '1m': { label: '1 Min', interval: 60 },
  '5m': { label: '5 Min', interval: 300 },
  '15m': { label: '15 Min', interval: 900 },
  '1h': { label: '1 Hour', interval: 3600 }
};

const BROKERS = [
  { 
    id: 'iifl_blaze', 
    name: 'IIFL Blaze (XTS)', 
    logo: '🔷',
    primary: true,
    description: 'Symphony Fintech XTS API - Interactive & Market Data',
    docs: 'https://ttblaze.iifl.com/doc/interactive/',
    fields: [
      { key: 'api_key', label: 'Interactive API Key', type: 'text', required: true, group: 'interactive' },
      { key: 'api_secret', label: 'Interactive Secret Key', type: 'password', required: true, group: 'interactive' },
      { key: 'market_api_key', label: 'Market Data API Key', type: 'text', required: false, group: 'market' },
      { key: 'market_secret_key', label: 'Market Data Secret Key', type: 'password', required: false, group: 'market' },
      { key: 'source', label: 'Source', type: 'text', default: 'WEBAPI', required: false, group: 'config' }
    ]
  },
  { 
    id: 'zerodha', 
    name: 'Zerodha', 
    logo: '🟢',
    primary: false,
    description: 'Kite Connect API',
    fields: [
      { key: 'api_key', label: 'API Key', type: 'text', required: true },
      { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
      { key: 'user_id', label: 'Client ID', type: 'text', required: true },
      { key: 'password', label: 'Password', type: 'password', required: true },
      { key: 'totp_secret', label: 'TOTP Secret', type: 'password', required: true }
    ]
  },
  { 
    id: 'upstox', 
    name: 'Upstox', 
    logo: '🔵',
    primary: false,
    description: 'Upstox Developer API',
    fields: [
      { key: 'api_key', label: 'API Key', type: 'text', required: true },
      { key: 'api_secret', label: 'API Secret', type: 'password', required: true },
      { key: 'user_id', label: 'User ID', type: 'text', required: true },
      { key: 'password', label: 'Access Token', type: 'password', required: true }
    ]
  },
  { 
    id: 'fyers', 
    name: 'FYERS', 
    logo: '🟡',
    primary: false,
    description: 'FYERS API v3',
    fields: [
      { key: 'api_key', label: 'App ID', type: 'text', required: true },
      { key: 'api_secret', label: 'Secret ID', type: 'password', required: true },
      { key: 'user_id', label: 'FY ID', type: 'text', required: true },
      { key: 'password', label: 'Password', type: 'password', required: true },
      { key: 'totp_secret', label: 'TOTP Secret', type: 'password', required: true }
    ]
  },
  { 
    id: 'dhan', 
    name: 'Dhan', 
    logo: '🟣',
    primary: false,
    description: 'Dhan HQ API',
    fields: [
      { key: 'api_key', label: 'Client ID', type: 'text', required: true },
      { key: 'api_secret', label: 'Access Token', type: 'password', required: true },
      { key: 'user_id', label: 'User ID', type: 'text', required: true },
      { key: 'password', label: 'Password (optional)', type: 'password', required: false }
    ]
  }
];

// ==================== DEFAULT STRATEGY (must be above component) ====================
const DEFAULT_STRATEGY = `MULTI-CHART ANALYSIS STRATEGY:

1. SPOT CHART ANALYSIS:
   - Identify trend direction (Higher Highs/Lows or Lower Highs/Lows)
   - Key support/resistance levels
   - VWAP position and slope

2. MARKET PROFILE ANALYSIS:
   - Value Area High (VAH) and Low (VAL)
   - Point of Control (POC) - highest volume price
   - Single prints and excess zones
   - Balance vs Imbalance state

3. ORDERFLOW ANALYSIS:
   - Cumulative Volume Delta (CVD) trend
   - Delta divergences with price
   - Absorption and imbalance patterns
   - Stacked imbalances for entry

4. OPTION CHAIN ANALYSIS:
   - Put-Call Ratio (PCR)
   - Max Pain level
   - OI buildup at strikes
   - IV changes

CONFLUENCE RULES:
- LONG: CVD rising + Price > POC + PCR > 1 + Bullish candle
- SHORT: CVD falling + Price < POC + PCR < 1 + Bearish candle
- NO_TRADE: Mixed signals or low confidence

RISK MANAGEMENT:
- Entry only on 3+ chart confluence
- SL based on VAL/VAH or recent swing
- Target based on SD bands or next OI cluster`;

// ==================== TOAST SYSTEM (React-safe) ====================
const toastQueue = [];
let toastListeners = [];
const addToast = (msg, type = 'info') => {
  const id = Date.now() + Math.random();
  toastQueue.push({ id, msg, type });
  toastListeners.forEach(fn => fn([...toastQueue]));
  setTimeout(() => {
    const idx = toastQueue.findIndex(t => t.id === id);
    if (idx !== -1) toastQueue.splice(idx, 1);
    toastListeners.forEach(fn => fn([...toastQueue]));
  }, 3000);
};

// ==================== MAIN COMPONENT ====================
const ChartVisionProX = () => {
  // Session state
  const [sessionId, setSessionId] = useState(null);
  const [isInitialized, setIsInitialized] = useState(false);
  
  // State
  const [tradingMode, setTradingMode] = useState('paper');
  const [isConnected, setIsConnected] = useState(false);
  const [brokerConnected, setBrokerConnected] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState('iifl_blaze'); // Default to IIFL
  const [brokerInfo, setBrokerInfo] = useState(null);
  const [isConnectingBroker, setIsConnectingBroker] = useState(false);
  
  // Chart states (4 charts)
  const [chartStreams, setChartStreams] = useState({
    spot: null,
    market_profile: null,
    orderflow: null,
    option_chain: null
  });
  const [chartCaptures, setChartCaptures] = useState({
    spot: null,
    market_profile: null,
    orderflow: null,
    option_chain: null
  });
  const [activeCharts, setActiveCharts] = useState(['spot', 'orderflow']);
  
  // Analysis
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isAutoMode, setIsAutoMode] = useState(false);
  const [countdown, setCountdown] = useState(300);
  const [currentSignal, setCurrentSignal] = useState(null);
  const [signalHistory, setSignalHistory] = useState([]);
  const [timeframe, setTimeframe] = useState('5m');
  
  // Trading
  const [position, setPosition] = useState(null);
  const [capital, setCapital] = useState(100000);
  const [pnl, setPnl] = useState(0);
  const [trades, setTrades] = useState([]);
  
  // Settings
  const [geminiKey, setGeminiKey] = useState('');
  const [brokerCredentials, setBrokerCredentials] = useState({});
  const [strategyContext, setStrategyContext] = useState(DEFAULT_STRATEGY);
  const [riskPercent, setRiskPercent] = useState(1);
  const [autoTrade, setAutoTrade] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  
  // Modals
  const [showSettings, setShowSettings] = useState(false);
  const [showBrokerModal, setShowBrokerModal] = useState(false);
  
  // Toast system (React-safe)
  const [toasts, setToasts] = useState([]);
  
  // Kill switch & safety
  const [killSwitch, setKillSwitch] = useState(false);
  const [wsStatus, setWsStatus] = useState('disconnected'); // connected, disconnected, reconnecting
  const analyzeDebounceRef = useRef(null);
  const wsReconnectAttempts = useRef(0);
  const maxWsReconnects = 10;
  
  // Subscribe to toast system
  useEffect(() => {
    const handler = (t) => setToasts([...t]);
    toastListeners.push(handler);
    return () => { toastListeners = toastListeners.filter(h => h !== handler); };
  }, []);
  
  // Refs
  const videoRefs = useRef({});
  const canvasRefs = useRef({});
  const wsRef = useRef(null);
  const autoIntervalRef = useRef(null);
  const previousAnalysisRef = useRef('');

  // ==================== SESSION INITIALIZATION ====================
  useEffect(() => {
    const initSession = async () => {
      try {
        // Check for existing session in localStorage (with safety)
        let existingSession = null;
        try { existingSession = localStorage.getItem('chartvision_session'); } catch(e) { /* localStorage unavailable */ }
        
        if (existingSession) {
          try {
            const response = await fetch(`${API_BASE_URL}/api/session/info`, {
              headers: { 'X-Session-ID': existingSession }
            });
            
            if (response.ok) {
              const sessionInfo = await response.json();
              setSessionId(existingSession);
              setBrokerConnected(sessionInfo.broker_connected);
              setTradingMode(sessionInfo.trading_mode || 'paper');
              if (sessionInfo.broker_type) setSelectedBroker(sessionInfo.broker_type);
              setIsInitialized(true);
              return;
            }
          } catch(e) { /* session invalid, create new */ }
        }
        
        // Create new session
        const response = await fetch(`${API_BASE_URL}/api/session/create`, { method: 'POST' });
        
        if (response.ok) {
          const data = await response.json();
          try { localStorage.setItem('chartvision_session', data.session_id); } catch(e) {}
          setSessionId(data.session_id);
        }
      } catch (err) {
        console.error('Session init error:', err);
      } finally {
        setIsInitialized(true);
      }
    };
    
    initSession();
  }, []);

  // ==================== WEBSOCKET (with exponential backoff) ====================
  useEffect(() => {
    if (!sessionId) return;
    let ws = null;
    let closed = false;
    
    const connectWS = () => {
      if (closed) return;
      
      setWsStatus('reconnecting');
      ws = new WebSocket(`${WS_URL}/${sessionId}`);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        setWsStatus('connected');
        wsReconnectAttempts.current = 0; // Reset on success
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'signal') handleSignal(data.data);
          if (data.type === 'error') addToast(data.message || 'Server error', 'error');
        } catch(e) { console.error('WS message parse error:', e); }
      };
      
      ws.onclose = () => {
        if (closed) return;
        setIsConnected(false);
        setWsStatus('disconnected');
        
        // Exponential backoff: 1s, 2s, 4s, 8s... max 30s
        if (wsReconnectAttempts.current < maxWsReconnects) {
          const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts.current), 30000);
          wsReconnectAttempts.current += 1;
          console.log(`WS reconnecting in ${delay/1000}s (attempt ${wsReconnectAttempts.current})`);
          setTimeout(connectWS, delay);
        } else {
          console.error('Max WS reconnection attempts reached');
          addToast('WebSocket connection lost. Refresh page.', 'error');
        }
      };
      
      ws.onerror = () => { /* onclose will handle reconnect */ };
      
      wsRef.current = ws;
    };
    
    connectWS();
    
    return () => {
      closed = true;
      if (ws) { try { ws.close(); } catch(e) {} }
    };
  }, [sessionId]);

  // ==================== SCREEN CAPTURE ====================
  const selectChartSource = async (chartType) => {
    try {
      // Stop existing stream
      if (chartStreams[chartType]) {
        chartStreams[chartType].getTracks().forEach(t => t.stop());
      }
      
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { cursor: 'never', displaySurface: 'window' },
        audio: false
      });
      
      setChartStreams(prev => ({ ...prev, [chartType]: stream }));
      
      if (videoRefs.current[chartType]) {
        videoRefs.current[chartType].srcObject = stream;
      }
      
      // Add to active charts if not already
      if (!activeCharts.includes(chartType)) {
        setActiveCharts(prev => [...prev, chartType]);
      }
      
      stream.getVideoTracks()[0].onended = () => {
        setChartStreams(prev => ({ ...prev, [chartType]: null }));
        setActiveCharts(prev => prev.filter(c => c !== chartType));
      };
      
      addToast(`${CHART_TYPES[chartType].label} connected`, 'success');
      
    } catch (err) {
      console.error('Screen capture error:', err);
      addToast('Screen capture failed', 'error');
    }
  };

  const captureFrame = useCallback((chartType) => {
    const video = videoRefs.current[chartType];
    if (!video || !chartStreams[chartType]) return null;
    
    const canvas = canvasRefs.current[chartType] || document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0);
    
    return canvas.toDataURL('image/jpeg', 0.9);
  }, [chartStreams]);

  const captureAllCharts = useCallback(() => {
    const captures = {};
    activeCharts.forEach(chartType => {
      const frame = captureFrame(chartType);
      if (frame) {
        captures[chartType] = frame;
      }
    });
    setChartCaptures(captures);
    return captures;
  }, [activeCharts, captureFrame]);

  // ==================== API HELPER ====================
  const apiCall = useCallback(async (endpoint, options = {}) => {
    const headers = {
      'Content-Type': 'application/json',
      ...(sessionId && { 'X-Session-ID': sessionId }),
      ...options.headers
    };
    
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers
    });
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Request failed' }));
      throw new Error(error.detail || 'Request failed');
    }
    
    return response.json();
  }, [sessionId]);

  // ==================== AI ANALYSIS (with debounce + kill switch) ====================
  const analyzeCharts = useCallback(async () => {
    if (killSwitch) {
      addToast('⛔ KILL SWITCH active – analysis blocked', 'error');
      return;
    }
    if (!geminiKey) {
      addToast('Configure Gemini API key first', 'error');
      setShowSettings(true);
      return;
    }
    
    // Debounce: prevent multiple rapid calls
    if (analyzeDebounceRef.current) {
      return;
    }
    analyzeDebounceRef.current = true;
    setTimeout(() => { analyzeDebounceRef.current = false; }, 3000);
    
    const captures = captureAllCharts();
    if (Object.keys(captures).length === 0) {
      addToast('No charts captured – select screen sources first', 'error');
      return;
    }
    
    setIsAnalyzing(true);
    
    try {
      const charts = Object.entries(captures).map(([chartType, imageData]) => ({
        chart_type: chartType,
        image_base64: imageData.split(',')[1],
        symbol: 'NIFTY',
        timeframe: timeframe
      }));
      
      const signal = await apiCall('/api/analyze/multi-chart', {
        method: 'POST',
        body: JSON.stringify({
          charts,
          strategy_context: strategyContext,
          previous_analysis: previousAnalysisRef.current
        })
      });
      
      handleSignal(signal);
      
    } catch (err) {
      console.error('Analysis error:', err);
      addToast(`Analysis failed: ${err.message}`, 'error');
    } finally {
      setIsAnalyzing(false);
    }
  }, [geminiKey, captureAllCharts, strategyContext, timeframe, apiCall, killSwitch]);

  const handleSignal = (signal) => {
    if (!signal || typeof signal !== 'object') return;
    
    // Validate signal fields
    if (!signal.decision || !['LONG', 'SHORT', 'NO_TRADE'].includes(signal.decision)) {
      signal.decision = 'NO_TRADE';
    }
    signal.confidence = Math.min(100, Math.max(0, signal.confidence || 0));
    signal.safety_score = Math.min(100, Math.max(0, signal.safety_score || 0));
    
    setCurrentSignal(signal);
    setSignalHistory(prev => [{ ...signal, timestamp: new Date().toISOString() }, ...prev].slice(0, 50));
    previousAnalysisRef.current = JSON.stringify(signal);
    
    // TTS
    if (ttsEnabled && 'speechSynthesis' in window) {
      try {
        const text = `${signal.decision} signal, ${signal.confidence} percent confidence`;
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.9;
        speechSynthesis.speak(utterance);
      } catch(e) { /* TTS not available */ }
    }
    
    // Auto trade (with kill switch check)
    if (!killSwitch && autoTrade && signal.confidence >= 70 && signal.safety_score >= 70) {
      if (signal.decision === 'LONG' || signal.decision === 'SHORT') {
        if (!position) {
          executeEntry(signal);
        }
      }
    }
  };

  // ==================== AUTO MODE ====================
  const toggleAutoMode = useCallback(() => {
    if (isAutoMode) {
      if (autoIntervalRef.current) clearInterval(autoIntervalRef.current);
      setIsAutoMode(false);
    } else if (activeCharts.length > 0) {
      setIsAutoMode(true);
      setCountdown(TIMEFRAMES[timeframe].interval);
      analyzeCharts();
      
      autoIntervalRef.current = setInterval(() => {
        setCountdown(prev => {
          if (prev <= 1) {
            analyzeCharts();
            return TIMEFRAMES[timeframe].interval;
          }
          return prev - 1;
        });
      }, 1000);
    }
  }, [isAutoMode, activeCharts, timeframe, analyzeCharts]);

  // ==================== TRADING (with kill switch + validation) ====================
  const executeEntry = async (signal) => {
    if (killSwitch) {
      addToast('⛔ KILL SWITCH active – trade blocked', 'error');
      return;
    }
    if (!signal.entry || signal.entry <= 0) {
      addToast('Invalid entry price – trade skipped', 'error');
      return;
    }
    
    const qty = Math.max(1, Math.floor((capital * riskPercent / 100) / signal.entry));
    
    try {
      const result = await apiCall('/api/orders/place', {
        method: 'POST',
        body: JSON.stringify({
          symbol: 'NIFTY',
          exchange: 'NFO',
          transaction_type: signal.decision === 'LONG' ? 'BUY' : 'SELL',
          order_type: 'MARKET',
          quantity: qty,
          product: 'MIS'
        })
      });
      
      if (result.status === 'success') {
        setPosition({
          side: signal.decision,
          entry: signal.entry,
          sl: signal.stoploss,
          target: signal.target1,
          qty
        });
        addToast(`${signal.decision} position opened @ ₹${signal.entry?.toFixed(2)}`, 'success');
      } else {
        addToast(result.message || 'Order failed', 'error');
      }
      
    } catch (err) {
      addToast(`Order failed: ${err.message}`, 'error');
    }
  };

  const exitPosition = async (reason = 'MANUAL') => {
    if (!position) return;
    
    try {
      await apiCall('/api/orders/place', {
        method: 'POST',
        body: JSON.stringify({
          symbol: 'NIFTY',
          exchange: 'NFO',
          transaction_type: position.side === 'LONG' ? 'SELL' : 'BUY',
          order_type: 'MARKET',
          quantity: position.qty,
          product: 'MIS'
        })
      });
      
      setPosition(null);
      addToast(`Position closed: ${reason}`, 'success');
      
    } catch (err) {
      addToast(`Exit failed: ${err.message}`, 'error');
    }
  };

  // ==================== BROKER CONNECTION ====================
  const connectBroker = async () => {
    if (!selectedBroker || !brokerCredentials[selectedBroker]) {
      addToast('Enter broker credentials first', 'error');
      return;
    }
    
    setIsConnectingBroker(true);
    
    try {
      const broker = BROKERS.find(b => b.id === selectedBroker);
      const creds = brokerCredentials[selectedBroker];
      
      // Build credentials object based on broker
      let payload = {
        broker: selectedBroker,
        api_key: creds.api_key || '',
        api_secret: creds.api_secret || '',
        user_id: creds.user_id || creds.api_key || '',
        password: creds.password || '',
        totp_secret: creds.totp_secret || null,
        source: creds.source || 'WEBAPI'
      };
      
      // Add IIFL Blaze specific market data credentials
      if (selectedBroker === 'iifl_blaze') {
        payload.market_api_key = creds.market_api_key || null;
        payload.market_secret_key = creds.market_secret_key || null;
      }
      
      const result = await apiCall('/api/broker/connect', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      
      if (result.status === 'success') {
        setBrokerConnected(true);
        setBrokerInfo(result);
        addToast(`Connected to ${broker?.name || selectedBroker}`, 'success');
        setShowBrokerModal(false);
      } else {
        throw new Error(result.message || 'Connection failed');
      }
      
    } catch (err) {
      addToast(`Broker connection failed: ${err.message}`, 'error');
    } finally {
      setIsConnectingBroker(false);
    }
  };

  const disconnectBroker = async () => {
    try {
      await apiCall('/api/broker/disconnect', { method: 'POST' });
      setBrokerConnected(false);
      setBrokerInfo(null);
      addToast('Broker disconnected', 'success');
    } catch (err) {
      addToast(`Disconnect failed: ${err.message}`, 'error');
    }
  };

  // ==================== UTILITIES ====================
  // toast is now the global addToast function (React state-based)
  const toast = addToast;

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // ==================== CLEANUP ====================
  useEffect(() => {
    return () => {
      if (autoIntervalRef.current) clearInterval(autoIntervalRef.current);
      Object.values(chartStreams).forEach(stream => {
        if (stream) stream.getTracks().forEach(t => t.stop());
      });
    };
  }, [chartStreams]);

  // ==================== RENDER ====================
  return (
    <div className="app">
      <style>{styles}</style>
      
      {/* Header */}
      <header className="header">
        <div className="logo">
          <div className="logo-icon">📊</div>
          <span className="logo-text">ChartVision <span>Pro X</span></span>
        </div>
        
        <div className="header-center">
          {/* Mode Switch */}
          <div className="mode-switch">
            <button 
              className={`mode-btn ${tradingMode === 'paper' ? 'active' : ''}`}
              onClick={() => setTradingMode('paper')}
            >
              📝 PAPER
            </button>
            <button 
              className={`mode-btn live ${tradingMode === 'live' ? 'active' : ''}`}
              onClick={() => {
                if (confirm('⚠️ LIVE MODE will place REAL orders. Continue?')) {
                  setTradingMode('live');
                }
              }}
            >
              🔴 LIVE
            </button>
          </div>
          
          {/* Capital Display */}
          <div className="capital-bar">
            <div className="capital-item">
              <div className="capital-label">CAPITAL</div>
              <div className="capital-value">₹{capital.toLocaleString()}</div>
            </div>
            <div className="capital-item">
              <div className="capital-label">P&L</div>
              <div className={`capital-value ${pnl >= 0 ? 'profit' : 'loss'}`}>
                {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(0)}
              </div>
            </div>
          </div>
          
          {/* Auto Mode Timer */}
          {isAutoMode && (
            <div className="scan-timer">
              <span className="pulse-dot"></span>
              NEXT: {formatTime(countdown)}
            </div>
          )}
        </div>
        
        <div className="header-controls">
          {/* Kill Switch */}
          <button 
            className={`btn ${killSwitch ? 'btn-danger' : ''}`}
            onClick={() => {
              setKillSwitch(!killSwitch);
              if (!killSwitch) {
                // Emergency stop: disable auto mode + auto trade
                if (isAutoMode) { if (autoIntervalRef.current) clearInterval(autoIntervalRef.current); setIsAutoMode(false); }
                setAutoTrade(false);
                addToast('⛔ KILL SWITCH ACTIVATED – all auto trading stopped', 'error');
              } else {
                addToast('Kill switch deactivated', 'success');
              }
            }}
          >
            {killSwitch ? '⛔ KILL ON' : '🛡️ KILL'}
          </button>
          <button 
            className="btn" 
            onClick={() => setShowBrokerModal(true)}
          >
            {brokerConnected ? '✅' : '🔗'} BROKER
          </button>
          <button className="btn" onClick={() => setShowSettings(true)}>
            ⚙️ SETTINGS
          </button>
          <button 
            className={`btn ${isAutoMode ? 'btn-danger' : 'btn-primary'}`}
            onClick={toggleAutoMode}
            disabled={activeCharts.length === 0 || killSwitch}
          >
            {isAutoMode ? '⏹️ STOP' : '▶️ AUTO'}
          </button>
          {/* WS Status */}
          <span style={{fontSize: '8px', padding: '4px 8px', borderRadius: '4px',
            background: wsStatus === 'connected' ? '#3fb950' : wsStatus === 'reconnecting' ? '#d29922' : '#f85149',
            color: wsStatus === 'connected' ? '#000' : '#fff'}}>
            {wsStatus === 'connected' ? '● LIVE' : wsStatus === 'reconnecting' ? '● RECONN' : '● OFF'}
          </span>
        </div>
      </header>
      
      {/* Main Content */}
      <main className="main-content">
        {/* Left Panel - Multi-Chart Grid */}
        <div className="charts-panel">
          <div className="charts-header">
            <span className="section-title">MULTI-CHART ANALYSIS</span>
            <span className="charts-count">{activeCharts.length}/4 Charts Active</span>
          </div>
          
          <div className="charts-grid">
            {Object.entries(CHART_TYPES).map(([type, config]) => (
              <ChartPanel
                key={type}
                chartType={type}
                config={config}
                stream={chartStreams[type]}
                isActive={activeCharts.includes(type)}
                onSelect={() => selectChartSource(type)}
                videoRef={el => videoRefs.current[type] = el}
              />
            ))}
          </div>
          
          {/* Analyze Button */}
          <button 
            className="analyze-btn"
            onClick={analyzeCharts}
            disabled={activeCharts.length === 0 || isAnalyzing}
          >
            {isAnalyzing ? (
              <>
                <div className="spinner"></div>
                ANALYZING {activeCharts.length} CHARTS...
              </>
            ) : (
              <>🧠 ANALYZE WITH GEMINI AI</>
            )}
          </button>
          
          {/* Timeframe Selection */}
          <div className="controls-row">
            <select 
              value={timeframe} 
              onChange={e => setTimeframe(e.target.value)}
              className="control-select"
            >
              {Object.entries(TIMEFRAMES).map(([key, { label }]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
            
            <button 
              className={`btn ${ttsEnabled ? 'btn-success' : ''}`}
              onClick={() => setTtsEnabled(!ttsEnabled)}
            >
              🔊 TTS {ttsEnabled ? 'ON' : 'OFF'}
            </button>
            
            <button 
              className={`btn ${autoTrade ? 'btn-warning' : ''}`}
              onClick={() => setAutoTrade(!autoTrade)}
            >
              🤖 AUTO-TRADE {autoTrade ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
        
        {/* Right Panel - Signal & Trading */}
        <div className="trading-panel">
          {/* Current Signal */}
          <SignalPanel signal={currentSignal} />
          
          {/* Position Panel */}
          {position && (
            <PositionPanel 
              position={position} 
              onExit={exitPosition}
            />
          )}
          
          {/* Signal History */}
          <div className="history-panel">
            <div className="panel-header">
              <span>📜 SIGNAL HISTORY</span>
              <span className="badge">{signalHistory.length}</span>
            </div>
            <div className="history-list">
              {signalHistory.slice(0, 10).map((signal, idx) => (
                <SignalHistoryItem key={idx} signal={signal} />
              ))}
              {signalHistory.length === 0 && (
                <div className="empty-state">
                  <span>📊</span>
                  <span>No signals yet</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
      
      {/* Settings Modal */}
      {showSettings && (
        <SettingsModal
          geminiKey={geminiKey}
          setGeminiKey={setGeminiKey}
          strategyContext={strategyContext}
          setStrategyContext={setStrategyContext}
          riskPercent={riskPercent}
          setRiskPercent={setRiskPercent}
          onClose={() => setShowSettings(false)}
          onSave={async () => {
            if (geminiKey) {
              await fetch(`${API_BASE_URL}/api/config/gemini`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: geminiKey })
              });
            }
            setShowSettings(false);
            addToast('Settings saved', 'success');
          }}
        />
      )}
      
      {/* Broker Modal */}
      {showBrokerModal && (
        <BrokerModal
          selectedBroker={selectedBroker}
          setSelectedBroker={setSelectedBroker}
          credentials={brokerCredentials}
          setCredentials={setBrokerCredentials}
          onConnect={connectBroker}
          onDisconnect={disconnectBroker}
          onClose={() => setShowBrokerModal(false)}
          isConnected={brokerConnected}
          isConnecting={isConnectingBroker}
          brokerInfo={brokerInfo}
        />
      )}
      
      {/* Toast Renderer (React-safe, no DOM manipulation) */}
      <div style={{position:'fixed',bottom:20,right:20,zIndex:10000,display:'flex',flexDirection:'column',gap:8}}>
        {toasts.map(t => (
          <div key={t.id} style={{padding:'12px 20px',
            background: t.type === 'error' ? '#f85149' : '#39d353',
            color:'white',borderRadius:8,fontSize:13,fontFamily:'inherit',
            animation:'slideIn 0.3s ease',boxShadow:'0 4px 12px rgba(0,0,0,0.3)'}}>
            {t.msg}
          </div>
        ))}
      </div>
    </div>
  );
};

// ==================== SUB-COMPONENTS ====================

const ChartPanel = ({ chartType, config, stream, isActive, onSelect, videoRef }) => (
  <div className={`chart-panel ${isActive ? 'active' : ''}`}>
    <div className="chart-header" style={{ borderColor: config.color }}>
      <span className="chart-icon">{config.icon}</span>
      <span className="chart-label">{config.label}</span>
      {isActive && <span className="live-badge">LIVE</span>}
    </div>
    <div className="chart-content">
      {stream ? (
        <video ref={videoRef} autoPlay muted className="chart-video" />
      ) : (
        <button className="select-btn" onClick={onSelect}>
          <span className="select-icon">+</span>
          <span>Select {config.label}</span>
          <span className="select-desc">{config.description}</span>
        </button>
      )}
    </div>
  </div>
);

const SignalPanel = ({ signal }) => {
  if (!signal) {
    return (
      <div className="signal-panel empty">
        <div className="empty-state">
          <span>🎯</span>
          <span>Awaiting Analysis</span>
        </div>
      </div>
    );
  }
  
  const decisionColors = {
    LONG: { bg: 'rgba(63, 185, 80, 0.2)', border: '#3fb950', text: '#3fb950' },
    SHORT: { bg: 'rgba(248, 81, 73, 0.2)', border: '#f85149', text: '#f85149' },
    NO_TRADE: { bg: 'rgba(210, 153, 34, 0.2)', border: '#d29922', text: '#d29922' }
  };
  
  const colors = decisionColors[signal.decision] || decisionColors.NO_TRADE;
  
  return (
    <div className="signal-panel">
      <div className="panel-header">
        <span>🎯 CURRENT SIGNAL</span>
        <span className="timestamp">{new Date().toLocaleTimeString()}</span>
      </div>
      
      <div 
        className="decision-badge"
        style={{ background: colors.bg, borderColor: colors.border, color: colors.text }}
      >
        {signal.decision}
      </div>
      
      <div className="metrics-grid">
        <div className="metric">
          <span className="metric-label">CONFIDENCE</span>
          <div className="metric-bar">
            <div 
              className="metric-fill"
              style={{ 
                width: `${signal.confidence}%`,
                background: signal.confidence >= 70 ? '#3fb950' : signal.confidence >= 40 ? '#d29922' : '#f85149'
              }}
            />
          </div>
          <span className="metric-value">{signal.confidence}%</span>
        </div>
        
        <div className="metric">
          <span className="metric-label">SAFETY</span>
          <div className="metric-bar">
            <div 
              className="metric-fill"
              style={{ 
                width: `${signal.safety_score}%`,
                background: signal.safety_score >= 70 ? '#3fb950' : signal.safety_score >= 40 ? '#d29922' : '#f85149'
              }}
            />
          </div>
          <span className="metric-value">{signal.safety_score}%</span>
        </div>
      </div>
      
      {signal.entry && (
        <div className="levels-grid">
          <div className="level">
            <span className="level-label">ENTRY</span>
            <span className="level-value">₹{signal.entry?.toFixed(2)}</span>
          </div>
          <div className="level sl">
            <span className="level-label">STOPLOSS</span>
            <span className="level-value">₹{signal.stoploss?.toFixed(2)}</span>
          </div>
          <div className="level target">
            <span className="level-label">TARGET 1</span>
            <span className="level-value">₹{signal.target1?.toFixed(2)}</span>
          </div>
          <div className="level">
            <span className="level-label">R:R</span>
            <span className="level-value">{signal.risk_reward}</span>
          </div>
        </div>
      )}
      
      {signal.reasoning?.length > 0 && (
        <div className="reasoning">
          <span className="reasoning-title">KEY OBSERVATIONS</span>
          {signal.reasoning.slice(0, 5).map((reason, idx) => (
            <div key={idx} className="reason-item">{reason}</div>
          ))}
        </div>
      )}
      
      {signal.warnings?.length > 0 && (
        <div className="warnings">
          {signal.warnings.map((warning, idx) => (
            <div key={idx} className="warning-item">⚠️ {warning}</div>
          ))}
        </div>
      )}
    </div>
  );
};

const PositionPanel = ({ position, onExit }) => (
  <div className={`position-panel ${position.side.toLowerCase()}`}>
    <div className="panel-header">
      <span>📍 ACTIVE POSITION</span>
      <span className={`position-side ${position.side.toLowerCase()}`}>{position.side}</span>
    </div>
    <div className="position-details">
      <div className="detail">
        <span>Entry</span>
        <span>₹{position.entry?.toFixed(2)}</span>
      </div>
      <div className="detail">
        <span>SL</span>
        <span className="sl">₹{position.sl?.toFixed(2)}</span>
      </div>
      <div className="detail">
        <span>Target</span>
        <span className="target">₹{position.target?.toFixed(2)}</span>
      </div>
      <div className="detail">
        <span>Qty</span>
        <span>{position.qty}</span>
      </div>
    </div>
    <button className="exit-btn" onClick={() => onExit('MANUAL')}>
      🚪 EXIT POSITION
    </button>
  </div>
);

const SignalHistoryItem = ({ signal }) => {
  const colors = {
    LONG: '#3fb950',
    SHORT: '#f85149',
    NO_TRADE: '#d29922'
  };
  
  return (
    <div className="history-item">
      <div className="history-time">
        {new Date(signal.timestamp).toLocaleTimeString()}
      </div>
      <div 
        className="history-decision"
        style={{ color: colors[signal.decision] }}
      >
        {signal.decision}
      </div>
      <div className="history-confidence">
        {signal.confidence}%
      </div>
    </div>
  );
};

const SettingsModal = ({ 
  geminiKey, setGeminiKey, 
  strategyContext, setStrategyContext,
  riskPercent, setRiskPercent,
  onClose, onSave 
}) => (
  <div className="modal-overlay" onClick={onClose}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <div className="modal-header">
        <span>⚙️ Settings</span>
        <button className="close-btn" onClick={onClose}>×</button>
      </div>
      
      <div className="modal-body">
        <div className="form-group">
          <label>Gemini API Key</label>
          <input 
            type="password"
            value={geminiKey}
            onChange={e => setGeminiKey(e.target.value)}
            placeholder="Enter your Gemini API key"
          />
          <small>Get your key from <a href="https://aistudio.google.com/apikey" target="_blank">Google AI Studio</a></small>
        </div>
        
        <div className="form-group">
          <label>Risk Per Trade (%)</label>
          <input 
            type="number"
            value={riskPercent}
            onChange={e => setRiskPercent(parseFloat(e.target.value))}
            min="0.1"
            max="5"
            step="0.1"
          />
        </div>
        
        <div className="form-group">
          <label>Strategy Context</label>
          <textarea 
            value={strategyContext}
            onChange={e => setStrategyContext(e.target.value)}
            rows={10}
          />
        </div>
      </div>
      
      <div className="modal-footer">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={onSave}>Save Settings</button>
      </div>
    </div>
  </div>
);

const BrokerModal = ({ 
  selectedBroker, setSelectedBroker,
  credentials, setCredentials,
  onConnect, onDisconnect, onClose, 
  isConnected, isConnecting, brokerInfo
}) => {
  const broker = BROKERS.find(b => b.id === selectedBroker);
  
  const updateCredential = (key, value) => {
    setCredentials(prev => ({
      ...prev,
      [selectedBroker]: { ...prev[selectedBroker], [key]: value }
    }));
  };
  
  // Group fields by category for IIFL Blaze
  const getGroupedFields = () => {
    if (!broker) return {};
    
    const groups = {};
    broker.fields.forEach(field => {
      const group = field.group || 'default';
      if (!groups[group]) groups[group] = [];
      groups[group].push(field);
    });
    return groups;
  };
  
  const groupedFields = getGroupedFields();
  const hasGroups = Object.keys(groupedFields).length > 1;
  
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal broker-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>🔗 Broker Connection</span>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        
        <div className="modal-body">
          {/* Connection Status */}
          {isConnected && brokerInfo && (
            <div className="connection-status connected">
              <span className="status-icon">✅</span>
              <div className="status-info">
                <strong>Connected to {broker?.name}</strong>
                {brokerInfo.user_id && <span>User: {brokerInfo.user_id}</span>}
                {brokerInfo.has_market_data && <span className="market-badge">📊 Market Data Active</span>}
              </div>
              <button className="btn btn-danger" onClick={onDisconnect}>Disconnect</button>
            </div>
          )}
          
          {/* Broker Selection */}
          <div className="broker-section">
            <label className="section-label">Select Broker</label>
            <div className="broker-grid">
              {BROKERS.map(b => (
                <button
                  key={b.id}
                  className={`broker-card ${selectedBroker === b.id ? 'selected' : ''} ${b.primary ? 'primary' : ''}`}
                  onClick={() => setSelectedBroker(b.id)}
                >
                  <span className="broker-logo">{b.logo}</span>
                  <span className="broker-name">{b.name}</span>
                  {b.primary && <span className="primary-badge">Recommended</span>}
                </button>
              ))}
            </div>
          </div>
          
          {/* Dynamic Credentials Form */}
          {broker && (
            <div className="credentials-form">
              <div className="broker-header">
                <span className="broker-logo-large">{broker.logo}</span>
                <div>
                  <h4>{broker.name}</h4>
                  <p>{broker.description}</p>
                  {broker.docs && (
                    <a href={broker.docs} target="_blank" rel="noopener noreferrer" className="docs-link">
                      📚 API Documentation
                    </a>
                  )}
                </div>
              </div>
              
              {/* IIFL Blaze - Grouped Fields */}
              {selectedBroker === 'iifl_blaze' ? (
                <>
                  {/* Interactive API Section */}
                  <div className="api-section">
                    <div className="api-section-header">
                      <span className="api-icon">⚡</span>
                      <span>Interactive API</span>
                      <span className="api-badge required">Required</span>
                    </div>
                    <div className="api-section-desc">For placing orders, managing positions & portfolio</div>
                    {groupedFields['interactive']?.map(field => (
                      <div className="form-group" key={field.key}>
                        <label>
                          {field.label}
                          {field.required && <span className="required">*</span>}
                        </label>
                        <input 
                          type={field.type}
                          value={credentials[selectedBroker]?.[field.key] || field.default || ''}
                          onChange={e => updateCredential(field.key, e.target.value)}
                          placeholder={`Enter ${field.label}`}
                          required={field.required}
                        />
                      </div>
                    ))}
                  </div>
                  
                  {/* Market Data API Section */}
                  <div className="api-section market">
                    <div className="api-section-header">
                      <span className="api-icon">📊</span>
                      <span>Market Data API</span>
                      <span className="api-badge optional">Optional</span>
                    </div>
                    <div className="api-section-desc">For live quotes, OHLC, option chain & instrument search</div>
                    {groupedFields['market']?.map(field => (
                      <div className="form-group" key={field.key}>
                        <label>{field.label}</label>
                        <input 
                          type={field.type}
                          value={credentials[selectedBroker]?.[field.key] || field.default || ''}
                          onChange={e => updateCredential(field.key, e.target.value)}
                          placeholder={`Enter ${field.label}`}
                        />
                      </div>
                    ))}
                    <div className="api-note">
                      💡 If not provided, Interactive API credentials will be used for market data
                    </div>
                  </div>
                  
                  {/* Config Section */}
                  {groupedFields['config']?.map(field => (
                    <div className="form-group" key={field.key}>
                      <label>{field.label}</label>
                      <input 
                        type={field.type}
                        value={credentials[selectedBroker]?.[field.key] || field.default || ''}
                        onChange={e => updateCredential(field.key, e.target.value)}
                        placeholder={field.default || `Enter ${field.label}`}
                      />
                    </div>
                  ))}
                </>
              ) : (
                /* Other Brokers - Simple Fields */
                broker.fields.map(field => (
                  <div className="form-group" key={field.key}>
                    <label>
                      {field.label}
                      {field.required && <span className="required">*</span>}
                    </label>
                    <input 
                      type={field.type}
                      value={credentials[selectedBroker]?.[field.key] || field.default || ''}
                      onChange={e => updateCredential(field.key, e.target.value)}
                      placeholder={`Enter ${field.label}`}
                      required={field.required}
                    />
                  </div>
                ))
              )}
              
              {/* IIFL Blaze specific help */}
              {selectedBroker === 'iifl_blaze' && (
                <div className="broker-help">
                  <h5>🔑 How to get IIFL Blaze API credentials:</h5>
                  <ol>
                    <li>Login to <a href="https://ttblaze.iifl.com" target="_blank">IIFL Blaze Portal</a></li>
                    <li>Go to <strong>Apps</strong> section</li>
                    <li>Create separate apps for <strong>Interactive</strong> and <strong>Market Data</strong></li>
                    <li>Copy the API Keys and Secret Keys for each</li>
                  </ol>
                  <div className="help-links">
                    <a href="https://ttblaze.iifl.com/doc/interactive/" target="_blank">📖 Interactive API Docs</a>
                    <a href="https://ttblaze.iifl.com/doc/marketdata/" target="_blank">📖 Market Data API Docs</a>
                  </div>
                </div>
              )}
              
              {/* Other broker help */}
              {selectedBroker === 'zerodha' && (
                <div className="broker-help">
                  <h5>🔑 TOTP Secret for Auto-Login:</h5>
                  <p>The TOTP Secret is the Base32 string shown when setting up 2FA. It looks like: <code>JBSWY3DPEHPK3PXP</code></p>
                </div>
              )}
            </div>
          )}
        </div>
        
        <div className="modal-footer">
          <button className="btn" onClick={onClose}>Cancel</button>
          {isConnected ? (
            <button className="btn btn-danger" onClick={onDisconnect}>
              🔌 Disconnect
            </button>
          ) : (
            <button 
              className="btn btn-primary" 
              onClick={onConnect}
              disabled={!selectedBroker || isConnecting}
            >
              {isConnecting ? (
                <>
                  <span className="spinner-small"></span>
                  Connecting...
                </>
              ) : (
                '🔗 Connect & Login'
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ==================== STYLES ====================
const styles = `
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');
  
  :root {
    --bg-primary: #06080d;
    --bg-secondary: #0d1117;
    --bg-tertiary: #161b22;
    --bg-card: #0d1117;
    --border-color: #30363d;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --accent-green: #3fb950;
    --accent-red: #f85149;
    --accent-blue: #58a6ff;
    --accent-yellow: #d29922;
    --accent-purple: #a371f7;
    --accent-cyan: #39d353;
  }
  
  * { margin: 0; padding: 0; box-sizing: border-box; }
  
  .app {
    font-family: 'JetBrains Mono', monospace;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
  
  /* Header */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 20px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
  }
  
  .logo {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  
  .logo-icon {
    width: 36px;
    height: 36px;
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
  }
  
  .logo-text {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 18px;
    font-weight: 700;
  }
  
  .logo-text span { color: var(--accent-cyan); }
  
  .header-center {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  
  .mode-switch {
    display: flex;
    background: var(--bg-tertiary);
    border-radius: 8px;
    padding: 3px;
    border: 1px solid var(--border-color);
  }
  
  .mode-btn {
    padding: 8px 16px;
    border: none;
    background: transparent;
    color: var(--text-muted);
    font-family: inherit;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    border-radius: 6px;
    transition: all 0.2s;
  }
  
  .mode-btn.active {
    background: var(--accent-cyan);
    color: var(--bg-primary);
  }
  
  .mode-btn.live.active {
    background: var(--accent-red);
    animation: pulse-live 2s infinite;
  }
  
  @keyframes pulse-live {
    0%, 100% { box-shadow: 0 0 0 0 rgba(248, 81, 73, 0.4); }
    50% { box-shadow: 0 0 0 6px rgba(248, 81, 73, 0); }
  }
  
  .capital-bar {
    display: flex;
    gap: 20px;
    padding: 8px 16px;
    background: var(--bg-tertiary);
    border-radius: 8px;
    border: 1px solid var(--border-color);
  }
  
  .capital-item { text-align: center; }
  .capital-label { font-size: 9px; color: var(--text-muted); text-transform: uppercase; }
  .capital-value { font-size: 13px; font-weight: 600; }
  .capital-value.profit { color: var(--accent-green); }
  .capital-value.loss { color: var(--accent-red); }
  
  .scan-timer {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    background: var(--bg-tertiary);
    border: 1px solid var(--accent-cyan);
    border-radius: 8px;
    font-size: 12px;
    color: var(--accent-cyan);
  }
  
  .pulse-dot {
    width: 8px;
    height: 8px;
    background: var(--accent-cyan);
    border-radius: 50%;
    animation: pulse 1.5s infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
  }
  
  .header-controls {
    display: flex;
    gap: 10px;
  }
  
  .btn {
    padding: 8px 14px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    font-family: inherit;
    font-size: 11px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
  }
  
  .btn:hover { border-color: var(--accent-cyan); }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-primary { background: var(--accent-blue); border-color: var(--accent-blue); }
  .btn-success { background: var(--accent-green); border-color: var(--accent-green); }
  .btn-danger { background: var(--accent-red); border-color: var(--accent-red); }
  .btn-warning { background: var(--accent-yellow); border-color: var(--accent-yellow); color: #000; }
  
  /* Main Content */
  .main-content {
    display: grid;
    grid-template-columns: 1fr 380px;
    flex: 1;
    overflow: hidden;
  }
  
  /* Charts Panel */
  .charts-panel {
    padding: 16px;
    overflow-y: auto;
    border-right: 1px solid var(--border-color);
  }
  
  .charts-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;
  }
  
  .section-title {
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  .charts-count {
    font-size: 11px;
    color: var(--accent-cyan);
  }
  
  .charts-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
    margin-bottom: 16px;
  }
  
  .chart-panel {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    overflow: hidden;
    transition: all 0.2s;
  }
  
  .chart-panel.active {
    border-color: var(--accent-cyan);
    box-shadow: 0 0 20px rgba(57, 211, 83, 0.1);
  }
  
  .chart-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    background: var(--bg-tertiary);
    border-bottom: 2px solid var(--border-color);
    font-size: 11px;
  }
  
  .chart-icon { font-size: 14px; }
  .chart-label { flex: 1; font-weight: 600; }
  
  .live-badge {
    font-size: 8px;
    padding: 3px 6px;
    background: var(--accent-green);
    color: #000;
    border-radius: 4px;
    font-weight: 700;
  }
  
  .chart-content {
    aspect-ratio: 16/10;
    background: var(--bg-primary);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  
  .chart-video {
    width: 100%;
    height: 100%;
    object-fit: contain;
  }
  
  .select-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 20px;
    background: transparent;
    border: 2px dashed var(--border-color);
    border-radius: 10px;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.2s;
    width: 80%;
  }
  
  .select-btn:hover {
    border-color: var(--accent-cyan);
    color: var(--accent-cyan);
  }
  
  .select-icon {
    font-size: 24px;
    font-weight: 300;
  }
  
  .select-desc {
    font-size: 9px;
    opacity: 0.7;
  }
  
  .analyze-btn {
    width: 100%;
    padding: 16px;
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-blue));
    border: none;
    border-radius: 10px;
    color: #000;
    font-family: inherit;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    margin-bottom: 12px;
    transition: all 0.2s;
  }
  
  .analyze-btn:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(57, 211, 83, 0.3);
  }
  
  .analyze-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .spinner {
    width: 18px;
    height: 18px;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  .controls-row {
    display: flex;
    gap: 10px;
  }
  
  .control-select {
    flex: 1;
    padding: 10px 12px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
    font-family: inherit;
    font-size: 11px;
    cursor: pointer;
  }
  
  /* Trading Panel */
  .trading-panel {
    background: var(--bg-secondary);
    padding: 16px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  .panel-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-color);
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .badge {
    padding: 2px 8px;
    background: var(--bg-tertiary);
    border-radius: 10px;
    font-size: 10px;
  }
  
  .timestamp {
    font-size: 10px;
    color: var(--text-muted);
  }
  
  /* Signal Panel */
  .signal-panel {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 16px;
  }
  
  .signal-panel.empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 200px;
  }
  
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    color: var(--text-muted);
    font-size: 12px;
  }
  
  .empty-state span:first-child {
    font-size: 32px;
    opacity: 0.5;
  }
  
  .decision-badge {
    display: inline-block;
    padding: 12px 24px;
    border: 2px solid;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 700;
    text-align: center;
    margin: 12px 0;
    letter-spacing: 2px;
  }
  
  .metrics-grid {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin: 16px 0;
  }
  
  .metric {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  
  .metric-label {
    font-size: 10px;
    color: var(--text-muted);
    width: 80px;
    text-transform: uppercase;
  }
  
  .metric-bar {
    flex: 1;
    height: 6px;
    background: var(--bg-tertiary);
    border-radius: 3px;
    overflow: hidden;
  }
  
  .metric-fill {
    height: 100%;
    transition: width 0.3s ease;
  }
  
  .metric-value {
    font-size: 12px;
    font-weight: 600;
    width: 40px;
    text-align: right;
  }
  
  .levels-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
    margin: 16px 0;
  }
  
  .level {
    padding: 10px;
    background: var(--bg-tertiary);
    border-radius: 8px;
    text-align: center;
  }
  
  .level-label {
    display: block;
    font-size: 9px;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 4px;
  }
  
  .level-value {
    font-size: 13px;
    font-weight: 600;
  }
  
  .level.sl .level-value { color: var(--accent-red); }
  .level.target .level-value { color: var(--accent-green); }
  
  .reasoning {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
  }
  
  .reasoning-title {
    display: block;
    font-size: 10px;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 10px;
  }
  
  .reason-item {
    padding: 8px 12px;
    margin-bottom: 6px;
    background: var(--bg-tertiary);
    border-left: 3px solid var(--accent-cyan);
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-secondary);
  }
  
  .warnings {
    margin-top: 12px;
  }
  
  .warning-item {
    padding: 8px 12px;
    margin-bottom: 6px;
    background: rgba(248, 81, 73, 0.1);
    border-left: 3px solid var(--accent-red);
    border-radius: 4px;
    font-size: 11px;
    color: var(--accent-red);
  }
  
  /* Position Panel */
  .position-panel {
    background: var(--bg-card);
    border: 2px solid var(--border-color);
    border-radius: 12px;
    padding: 16px;
  }
  
  .position-panel.long { border-color: var(--accent-green); }
  .position-panel.short { border-color: var(--accent-red); }
  
  .position-side {
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
  }
  
  .position-side.long { background: var(--accent-green); color: #000; }
  .position-side.short { background: var(--accent-red); color: #fff; }
  
  .position-details {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    margin: 12px 0;
  }
  
  .detail {
    display: flex;
    justify-content: space-between;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 6px;
    font-size: 11px;
  }
  
  .detail .sl { color: var(--accent-red); }
  .detail .target { color: var(--accent-green); }
  
  .exit-btn {
    width: 100%;
    padding: 12px;
    background: var(--accent-red);
    border: none;
    border-radius: 8px;
    color: white;
    font-family: inherit;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  
  /* History Panel */
  .history-panel {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  
  .history-panel .panel-header {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-color);
  }
  
  .history-list {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }
  
  .history-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: var(--bg-tertiary);
    border-radius: 8px;
    margin-bottom: 6px;
    font-size: 11px;
  }
  
  .history-time {
    color: var(--text-muted);
    width: 70px;
  }
  
  .history-decision {
    flex: 1;
    font-weight: 600;
  }
  
  .history-confidence {
    color: var(--text-secondary);
  }
  
  /* Modals */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    backdrop-filter: blur(4px);
  }
  
  .modal {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    width: 90%;
    max-width: 500px;
    max-height: 90vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  
  .broker-modal {
    max-width: 600px;
  }
  
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border-color);
    font-size: 14px;
    font-weight: 600;
  }
  
  .close-btn {
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 24px;
    cursor: pointer;
    line-height: 1;
  }
  
  .close-btn:hover { color: var(--text-primary); }
  
  .modal-body {
    padding: 20px;
    overflow-y: auto;
    flex: 1;
  }
  
  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 20px;
    background: var(--bg-tertiary);
    border-top: 1px solid var(--border-color);
  }
  
  .form-group {
    margin-bottom: 16px;
  }
  
  .form-group label {
    display: block;
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 6px;
  }
  
  .form-group input,
  .form-group textarea {
    width: 100%;
    padding: 10px 12px;
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
    font-family: inherit;
    font-size: 12px;
  }
  
  .form-group input:focus,
  .form-group textarea:focus {
    outline: none;
    border-color: var(--accent-cyan);
  }
  
  .form-group small {
    display: block;
    margin-top: 6px;
    font-size: 10px;
    color: var(--text-muted);
  }
  
  .form-group small a {
    color: var(--accent-blue);
    text-decoration: none;
  }
  
  /* Broker Grid */
  .broker-section {
    margin-bottom: 20px;
  }
  
  .section-label {
    display: block;
    font-size: 11px;
    color: var(--text-muted);
    text-transform: uppercase;
    margin-bottom: 10px;
  }
  
  .broker-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    margin-bottom: 20px;
  }
  
  .broker-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 16px 12px;
    background: var(--bg-tertiary);
    border: 2px solid var(--border-color);
    border-radius: 10px;
    cursor: pointer;
    transition: all 0.2s;
    position: relative;
  }
  
  .broker-card:hover {
    border-color: var(--accent-cyan);
  }
  
  .broker-card.selected {
    border-color: var(--accent-cyan);
    background: rgba(57, 211, 83, 0.1);
  }
  
  .broker-card.primary {
    border-color: var(--accent-blue);
  }
  
  .broker-card.primary.selected {
    border-color: var(--accent-cyan);
  }
  
  .primary-badge {
    position: absolute;
    top: -8px;
    right: -8px;
    font-size: 8px;
    padding: 3px 6px;
    background: var(--accent-blue);
    color: white;
    border-radius: 4px;
    text-transform: uppercase;
  }
  
  .broker-logo {
    font-size: 24px;
  }
  
  .broker-name {
    font-size: 11px;
    font-weight: 600;
  }
  
  .credentials-form {
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
  }
  
  .broker-header {
    display: flex;
    gap: 16px;
    margin-bottom: 20px;
    padding: 16px;
    background: var(--bg-tertiary);
    border-radius: 10px;
  }
  
  .broker-logo-large {
    font-size: 40px;
  }
  
  .broker-header h4 {
    font-size: 16px;
    margin: 0 0 4px 0;
    color: var(--accent-cyan);
  }
  
  .broker-header p {
    font-size: 12px;
    color: var(--text-muted);
    margin: 0 0 8px 0;
  }
  
  .docs-link {
    font-size: 11px;
    color: var(--accent-blue);
    text-decoration: none;
  }
  
  .docs-link:hover {
    text-decoration: underline;
  }
  
  .required {
    color: var(--accent-red);
    margin-left: 4px;
  }
  
  .broker-help {
    margin-top: 20px;
    padding: 16px;
    background: rgba(88, 166, 255, 0.1);
    border: 1px solid rgba(88, 166, 255, 0.3);
    border-radius: 8px;
    font-size: 11px;
  }
  
  .broker-help h5 {
    margin: 0 0 10px 0;
    color: var(--accent-blue);
  }
  
  .broker-help ol {
    margin: 0;
    padding-left: 20px;
    color: var(--text-secondary);
  }
  
  .broker-help li {
    margin-bottom: 6px;
  }
  
  .broker-help p {
    margin: 0;
    color: var(--text-secondary);
  }
  
  .broker-help code {
    background: var(--bg-primary);
    padding: 2px 6px;
    border-radius: 4px;
    font-family: inherit;
  }
  
  .broker-help a {
    color: var(--accent-cyan);
  }
  
  .help-links {
    display: flex;
    gap: 16px;
    margin-top: 12px;
  }
  
  .help-links a {
    font-size: 11px;
    color: var(--accent-blue);
    text-decoration: none;
  }
  
  .help-links a:hover {
    text-decoration: underline;
  }
  
  /* API Sections for IIFL Blaze */
  .api-section {
    margin-bottom: 20px;
    padding: 16px;
    background: var(--bg-tertiary);
    border-radius: 10px;
    border: 1px solid var(--border-color);
  }
  
  .api-section.market {
    border-color: rgba(88, 166, 255, 0.3);
    background: rgba(88, 166, 255, 0.05);
  }
  
  .api-section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 13px;
    font-weight: 600;
  }
  
  .api-icon {
    font-size: 16px;
  }
  
  .api-badge {
    font-size: 9px;
    padding: 3px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    margin-left: auto;
  }
  
  .api-badge.required {
    background: var(--accent-green);
    color: #000;
  }
  
  .api-badge.optional {
    background: var(--accent-blue);
    color: white;
  }
  
  .api-section-desc {
    font-size: 11px;
    color: var(--text-muted);
    margin-bottom: 16px;
  }
  
  .api-note {
    font-size: 10px;
    color: var(--accent-blue);
    padding: 10px;
    background: rgba(88, 166, 255, 0.1);
    border-radius: 6px;
    margin-top: 12px;
  }
  
  .market-badge {
    display: inline-block;
    font-size: 10px;
    padding: 3px 8px;
    background: var(--accent-blue);
    color: white;
    border-radius: 4px;
    margin-left: 8px;
  }
  
  .connection-status {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    margin-bottom: 20px;
    border-radius: 10px;
  }
  
  .connection-status.connected {
    background: rgba(63, 185, 80, 0.1);
    border: 1px solid var(--accent-green);
  }
  
  .status-icon {
    font-size: 24px;
  }
  
  .status-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .status-info strong {
    color: var(--accent-green);
    font-size: 13px;
  }
  
  .status-info span {
    font-size: 11px;
    color: var(--text-muted);
  }
  
  .spinner-small {
    width: 14px;
    height: 14px;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    display: inline-block;
    margin-right: 8px;
  }
  
  .credentials-form h4 {
    font-size: 13px;
    margin-bottom: 16px;
    color: var(--accent-cyan);
  }
  
  /* Toast Animation */
  @keyframes slideIn {
    from {
      transform: translateX(100%);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
`;

export default ChartVisionProX;
