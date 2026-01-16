import subprocess
import time
import webbrowser
import sys
import os

def run_command_bg(args):
    """백그라운드에서 명령어 실행 (출력 숨김)"""
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def main():
    # 현재 실행 중인 파이썬 인터프리터 사용 (가상환경 보장)
    python_exe = sys.executable
    print(f"🚀 Starting ShortsMaker Services...")

    # 1. Prefect Server 시작
    print("1. Starting Prefect Server...")
    server_process = run_command_bg([python_exe, "-m", "prefect", "server", "start"])
    
    # 서버가 뜰 때까지 잠시 대기
    time.sleep(5)

    # 2. API URL 설정
    print("2. Configuring API URL...")
    subprocess.run([python_exe, "-m", "prefect", "config", "set", "PREFECT_API_URL=http://127.0.0.1:4200/api"])

    # 3. Worker 시작
    print("3. Starting Worker (local-process-pool)...")
    worker_process = run_command_bg([python_exe, "-m", "prefect", "worker", "start", "--pool", "local-process-pool"])

    # 4. 브라우저 열기
    print("4. Opening Dashboard...")
    webbrowser.open("http://127.0.0.1:4200/deployments")

    print("✅ All services are running!")
    print("Press Ctrl+C (or Stop button) to stop.")

    try:
        # 프로세스가 종료될 때까지 대기
        server_process.wait()
        worker_process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # 종료 시 자식 프로세스 정리
        print("\n🛑 Stopping services...")
        server_process.terminate()
        worker_process.terminate()
        print("Goodbye!")

if __name__ == "__main__":
    main()
