from typing import Dict, List
import random
import os

from tool.util import read_yaml, log_dbg, log_err


class Meme:
    # 错误表情包路径
    meme_error_path: str = "./run/meme/error/"
    # 默认表情包路径
    meme_common_path: str = "./run/meme/common/"
    meme: Dict[str, List]

    def __init__(self):
        try:
            self.meme = {}
            self.meme["error"] = self.get_file_paths(self.meme_error_path)
            self.meme["common"] = self.get_file_paths(self.meme_common_path)

        except Exception as e:
            log_err("fail to load meme:" + str(e))

    def get_file_paths(self, folder_path):
        """
        将指定文件夹下的所有文件的绝对路径读取到一个 list 中。
        """
        file_paths = []
        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                # 拼接文件的绝对路径
                filepath = os.path.join(root, filename)
                # set to abs path
                filepath = os.path.abspath(filepath)
                file_paths.append(filepath)
        return file_paths

    @property
    def error(self):
        try:
            return random.choice(self.meme["error"])
        except:
            return ""

    @property
    def common(self):
        try:
            return random.choice(self.meme["common"])
        except:
            return ""


class Config:
    go_cqhttp_config: str = "./run/config.yml"
    setting_config: str = "./run/setting.yml"
    memory_config: str = "./run/memory.yml"
    memory_model_file: str = "./run/memory.pt"
    task_config_name: str = "task.yml"
    setting: dict = {}
    meme: Meme
    max_requestion: int = 1024

    def __init__(self) -> None:
        self.meme = Meme()
    
    @classmethod
    def create_file_and_path(cls, file) -> dict:
        try:
            if not file or not len(file):
                raise Exception("fail name is empty")
                        
            file_path = file
            # 检查文件夹是否存在，如果不存在则创建文件夹和文件
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path))
                with open(file_path, 'w'):
                    pass
                log_dbg(f"file '{file_path}' create done")
            else:
                # 文件夹已存在，检查文件是否存在
                if not os.path.exists(file_path):
                    # 文件不存在，创建新文件
                    with open(file_path, 'w'):
                        pass
                    log_dbg(f"file '{file_path}' create done")
                else:
                    log_dbg(f"file '{file_path}' exist")
        except Exception as e:
            log_dbg(f"fail to create: {e}")

    @classmethod
    def load_memory(cls) -> dict:
        try:
            obj = read_yaml(Config.memory_config)
            mem = {}
            mem["openai_conversation_id"] = obj.get("openai_conversation_id", "")
            mem["idx"] = obj.get("idx", 0)
            mem["pool"] = obj.get("pool", [])

            log_dbg("cfg load memory done.")

            # log_dbg('mem: ' + str(mem))

            try:
                label = 0
                for iter in mem["pool"]:
                    if not iter:
                        continue
                    iter["idx"] = label

                    label += 1
            except Exception as e:
                log_err("fail to set label: " + str(e))
                mem["pool"] = []
            # log_dbg('mem: ' + str(mem))

            return mem
        except Exception as e:
            log_err("fail to load memory: " + str(e))
            return {}

    @classmethod
    def load_task(cls, session_id = 'default') -> dict:
        try:
            task_config_file = f"./run/database/{session_id}/{Config.task_config_name}"
            obj = read_yaml(task_config_file)
            task = {}

            task["tasks"] = obj.get("tasks", {})
            task["now_task_id"] = obj.get("now_task_id", "1")
            task["timestamp"] = obj.get("timestamp", 1)
            task["running"] = obj.get("running", [])
            task["notes"] = obj.get("notes", [])

            log_dbg("cfg load task done.")

            return task
        except Exception as e:
            log_err("fail to load task: " + str(e))
            return {}

    @classmethod
    def load_setting(cls, type) -> dict:
        try:
            obj = read_yaml(Config.setting_config)
        except Exception as e:
            log_err(f"fail to load setting: {e}")
            return {}

        setting = {}
        try:
            setting = obj.get(type, {})
        except Exception as e:
            log_err(f"fail to load setting[{type}]: {e}")
            setting = {}

        return setting
