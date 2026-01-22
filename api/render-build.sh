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
  
  # Unlock the binary
  chmod +x $STORAGE_DIR/chrome/opt/google/chrome/chrome
  cd -
else
  echo "...Using Chrome from cache"
fi

# INSTALL SYSTEM LIBRARIES (The Missing Piece)
echo "...Installing System Libraries"
# This ensures Render's environment has what it needs to run a browser
pip install -r requirements.txt

echo "...Installing Selenium Drivers"
python -c "from webdriver_manager.chrome import ChromeDriverManager; ChromeDriverManager().install()"
