
from tool.util import log_err, log_dbg

class Sandbox():
    # 容器类型
    # system:       不安全用法
    # proot-distro  termux
    # docker
    model: str = 'system'
    sandbox_file: str = './run/sandbox.py'

    def __init__(self):
        pass
    
    def write_code(code: str):
        try:
            file = open(Sandbox.sandbox_file, 'w', encoding='utf-8')
            file.write(code)
            file.close()
            log_dbg("write code done")
            return True
        except Exception as e:
            log_err(f"fail to write code: {str(e)}")
        return False

    def run_code():
        import subprocess
        try:
            result = subprocess.run(
                ["python3.9", Sandbox.sandbox_file],
                stdout=subprocess.PIPE,
            )
            return result.stdout.decode('utf-8')
        except Exception as e:
            log_err(f"fail to exec code: {str(e)}")
        return 'system error: exec code failed.'
    