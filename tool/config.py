from typing import Dict, List
import random
import os

from tool.util import read_yaml, log_dbg, log_err

class Meme:
    # 错误表情包路径
    meme_error_path: str = './run/meme/error/'
    # 默认表情包路径
    meme_common_path: str = './run/meme/common/'
    meme: Dict[str, List]

    def __init__(self):
        try:
            self.meme = {}
            self.meme['error'] = self.get_file_paths(self.meme_error_path)
            self.meme['common'] = self.get_file_paths(self.meme_common_path)
            
        except Exception as e:
            log_err('fail to load meme:' + str(e))

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
            return random.choice(self.meme['error'])
        except:
            return ''
    
    @property
    def common(self):
        try:
            return random.choice(self.meme['common'])
        except:
            return ''
    
class Config:
    go_cqhttp_config: str = './run/config.yml'
    setting_config: str = './run/setting.yml'
    memory_config: str = './run/memory.yml'
    memory_model_file: str = './run/memory.pt'
    setting: dict = {}
    meme: Meme
    max_requestion: int = 1024

    def __init__(self) -> None:
        try:
            setting_config = read_yaml(self.setting_config)
            self.setting = self.__load_setting(setting_config)
        except:
            self.setting = {}
        self.meme = Meme()
        
    def load_memory(self) -> dict:
        try:
            obj = read_yaml(self.memory_config)
            mem = {}
            mem['openai_conversation_id'] = obj.get('openai_conversation_id', '')
            mem['idx'] = obj.get('idx', 0)
            mem['pool'] = obj.get('pool', [])

            log_dbg('cfg load memory done.')

            #log_dbg('mem: ' + str(mem))

            try:
                label = 0
                for iter in mem['pool']:
                    if not iter:
                        continue
                    iter['label'] = label
                    label += 1
            except Exception as e:
                log_err('fail to set label: ' + str(e))
                mem['pool'] = []
            #log_dbg('mem: ' + str(mem))
           
            return mem
        except Exception as e:
            log_err('fail to load memory: ' + str(e))
            return {}

    def __load_setting(self, obj) -> dict:
        if not obj:
            return {}

        s = {}

        try:
            s['qq'] = obj.get('qq', [])
        except Exception as e:
            s['qq'] = []
            log_err('fail to load setting: ' + str(e))
        try:
            s['openai'] = obj.get('openai', [])
        except Exception as e:
            s['openai'] = []
            log_err('fail to load setting: ' + str(e))
        try:
            s['bing'] = obj.get('bing', [])
        except Exception as e:
            s['bing'] = []
            log_err('fail to load setting: ' + str(e))
        try:
            s['bard'] = obj.get('bard', [])
        except Exception as e:
            s['bard'] = []
            log_err('fail to load setting: ' + str(e))
        try:
            s['aimi'] = obj.get('aimi', [])
        except Exception as e:
            s['aimi'] = []
            log_err('fail to load setting: ' + str(e))
        
        return s
        
    
config = Config()
