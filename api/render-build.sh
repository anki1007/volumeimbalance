#!/usr/bin/env bash
# Exit on error
set -o errexit

STORAGE_DIR=/opt/render/project/.render

if [[ ! -d $STORAGE_DIR/chrome ]]; then
  echo "...Downloading Chrome"
  mkdir -p $STORAGE_DIR/chrome
  cd $STORAGE_DIR/chrome
  wget -P ./ https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  dpkg -x ./google-chrome-stable_current_amd64.deb $STORAGE_DIR/chrome
  rm ./google-chrome-stable_current_amd64.deb
  
  # Unlock permissions
  chmod +x $STORAGE_DIR/chrome/opt/google/chrome/chrome
  cd -
else
  echo "...Using Chrome from cache"
fi

# Clean old environment and install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Force update the driver
echo "...Updating Selenium Driver to match Chrome 144"
python -c "from webdriver_manager.chrome import ChromeDriverManager; ChromeDriverManager().install()"
