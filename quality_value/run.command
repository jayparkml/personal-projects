#!/bin/bash
# quality-value monthly monitor launcher
# Double-click to open Terminal and run the monitor.

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Python 경로 확인
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "Python을 찾을 수 없습니다. Python 3.11+ 를 설치해주세요."
    read -n 1 -r -p "아무 키나 누르면 닫힙니다..."
    osascript -e 'tell application "Terminal" to close front window' &
    exit 1
fi

# 필요한 패키지 확인 및 설치
echo "패키지 확인 중..."
$PYTHON -c "import yfinance, pandas, requests" 2>/dev/null || {
    echo "필요한 패키지 설치 중 (yfinance, pandas, requests)..."
    $PYTHON -m pip install yfinance pandas requests --quiet
}

echo ""
PYTHONUNBUFFERED=1 $PYTHON -u quality_value_monthly_monitor.py

echo ""
read -n 1 -r -p "아무 키나 누르면 창이 닫힙니다..."
osascript -e 'tell application "Terminal" to close front window' &
