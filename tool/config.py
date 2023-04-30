from tool.util import read_yaml, write_yaml, log_dbg, log_err

class Config:
    go_cqhttp_config: str = './run/config.yml'
    setting_config: str = './run/setting.yml'
    memory_config: str = './run/memory.yml'
    setting: dict = {}

    def __init__(self) -> None:
        setting_config = read_yaml(self.setting_config)
        self.setting = self.__load_setting(setting_config)
        
    def load_memory(self) -> dict:
        obj = read_yaml(self.memory_config)
        try:
            mem = {}
            mem['openai_conversation_id'] = obj.get('openai_conversation_id', '')
            mem['idx'] = obj.get('idx', 0)
            mem['pool'] = obj.get('pool', [])

            log_dbg('cfg load memory done.')
            #log_dbg('mem: ' + str(mem))
            
            return mem
        except Exception as e:
            log_err('fail to load memory: ' + str(e))
            return {}

    def __load_setting(self, obj) -> dict:
        if not obj:
            return {}
        
        try:
            s = {}
            s['qq'] = obj.get('qq', [])
            s['openai_config'] = obj.get('openai_config', [])
            s['aimi'] = obj.get('aimi', [])
            
            log_dbg('cfg load setting done.')
            
            return s
        except Exception as e:
            log_err('fail to load setting: ' + str(e))
            return []
    
        
    
config = Config()
