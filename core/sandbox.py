import sys
from pydantic import BaseModel, constr
from typing import List

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
    model: str = "docker"
    sandbox_file: str = "sandbox.py"
    sandbox_path: str = "./run/sandbox/"

    def __init__(self):
        pass

    def write_code(code: str):
        try:
            file = open(
                Sandbox.sandbox_path + Sandbox.sandbox_file, "w", encoding="utf-8"
            )
            file.write(str(code))
            file.close()
            log_dbg("write code done")
            return True
        except Exception as e:
            log_err(f"fail to write code: {str(e)}")
        return False

    def __run_cmd(cmd: List[str]):
        import subprocess
        result = subprocess.run(
            cmd,
            cwd=Sandbox.sandbox_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result

    def __run_system_code():
        run = RunCodeReturn(
            returncode=-1,
            stdout="",
            stderr=""
        )
    
        result = Sandbox.__run_cmd(
            [sys.executable, Sandbox.sandbox_file]
        )
        run.returncode = int(result.returncode)
        run.stdout = str(result.stdout.decode("utf-8"))
        run.stderr = str(result.stderr.decode("utf-8"))
    
        return run

    def __run_docker_code():
        run = RunCodeReturn(
            returncode=-1,
            stdout="",
            stderr=""
        )

        # create requirements.txt
        # request: pipreqs
        result = Sandbox.__run_cmd(
            ["pipreqs", "--force"]
        )
        if result.returncode != 0:
            raise Exception(f"fail to create requirements.txt : {str(result.stderr)}")

        result = Sandbox.__run_cmd(
            ["docker", "build", "-t", "sandbox", "."]
        )
        if result.returncode != 0:
            raise Exception("build docker fail")

        build_log = result.stdout.decode('utf-8')
        if len(build_log):
            log_dbg(f"docker build done {build_log}")

        # run code.
        result = Sandbox.__run_cmd(
            ["docker", "run", "--rm", "sandbox"]
        )

        run.returncode = int(result.returncode)
        run.stdout = str(result.stdout.decode("utf-8"))
        run.stderr = str(result.stderr.decode("utf-8"))

        return run

    def run_code() -> RunCodeReturn:

        max_return_len = 2048
        run = RunCodeReturn(
            returncode=-1,
            stdout="",
            stderr=""
        )

        try:
            if Sandbox.model == "system":
                run = Sandbox.__run_system_code()
            elif Sandbox.model == "docker":
                run = Sandbox.__run_docker_code()

            if not len(run.stdout):
                run.returncode = -1
                if not len(run.stderr):
                    run.stderr = "你没有用 `print` 打印运行结果, 请添加 `print` 后才能重试 . "
            if len(run.stdout) > max_return_len:
                log_err(f"run stdout over limit: {str(len(run.stdout))}")
                run.stdout = run.stdout[max_return_len:]
            if len(run.stderr) > max_return_len:
                log_err(f"run stderr over limit: {str(len(run.stderr))}")
                run.stderr = run.stderr[max_return_len:]
            return run
        except Exception as e:
            log_err(f"fail to exec code: {str(e)}")
            run.stderr = str(e)
        return run
