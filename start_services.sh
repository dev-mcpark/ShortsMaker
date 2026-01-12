#!/bin/bash

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Starting ShortsMaker Services...${NC}"

# 1. Prefect Server 시작 (백그라운드)
echo -e "${GREEN}1. Starting Prefect Server...${NC}"
prefect server start > /dev/null 2>&1 &
SERVER_PID=$!
sleep 5 # 서버가 뜰 때까지 잠시 대기

# 2. Prefect API URL 설정
echo -e "${GREEN}2. Configuring API URL...${NC}"
prefect config set PREFECT_API_URL="http://127.0.0.1:4200/api"

# 3. Worker 시작 (백그라운드)
echo -e "${GREEN}3. Starting Worker (local-process-pool)...${NC}"
prefect worker start --pool "local-process-pool" > /dev/null 2>&1 &
WORKER_PID=$!

# 4. 브라우저 열기
echo -e "${GREEN}4. Opening Dashboard...${NC}"
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://127.0.0.1:4200/deployments"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open "http://127.0.0.1:4200/deployments"
fi

echo -e "${BLUE}✅ All services are running!${NC}"
echo -e "Press ${BLUE}Ctrl+C${NC} to stop all services."

# 종료 시그널(Ctrl+C) 처리
cleanup() {
    echo -e "\n${BLUE}🛑 Stopping services...${NC}"
    kill $SERVER_PID
    kill $WORKER_PID
    echo -e "${GREEN}Goodbye!${NC}"
    exit
}

trap cleanup SIGINT

# 스크립트가 종료되지 않게 대기
wait
