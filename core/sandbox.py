import sys
from pydantic import BaseModel, constr

from tool.util import log_err, log_dbg


class RunCodeReturn(BaseModel):
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class Sandbox:
    # 容器类型
    # system:       不安全用法
    # proot-distro  termux
    # docker
    model: str = "system"
    sandbox_file: str = "./run/sandbox.py"

    def __init__(self):
        pass

    def write_code(code: str):
        try:
            file = open(Sandbox.sandbox_file, "w", encoding="utf-8")
            file.write(str(code))
            file.close()
            log_dbg("write code done")
            return True
        except Exception as e:
            log_err(f"fail to write code: {str(e)}")
        return False

    def run_code() -> RunCodeReturn:
        import subprocess

        max_return_len = 2048
        run: RunCodeReturn = RunCodeReturn(returncode=-1, stdout="", stderr="")

        result = ""
        try:
            result = subprocess.run(
                [sys.executable, Sandbox.sandbox_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            run.returncode = int(result.returncode)
            run.stdout = str(result.stdout.decode("utf-8"))
            run.stderr = str(result.stderr.decode("utf-8"))
            if not len(run.stdout):
                run.returncode = -1
            if len(run.stdout) > max_return_len:
                log_err(f"run stdout over limit: {str(len(run.stdout))}")
                run.stdout = run.stdout[max_return_len:]
            if len(run.stderr) > max_return_len:
                log_err(f"run stderr over limit: {str(len(run.stderr))}")
                run.stderr = run_stderr[max_return_len:]
            return run
        except Exception as e:
            log_err(f"fail to exec code: {str(e)}")
            run["stderr"] = str(e)
        return run
