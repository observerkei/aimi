import os
import importlib.util
from typing import Any, List, Generator, Dict

from tool.util import log_info, log_err, log_dbg
from tool.config import config

# call bot_ plugin
class Bot:
    # This has to be globally unique
    type: str = 'public_name'
    trigger: str = '#public_name'
    bot: Any

    def __init__(
        self
    ):
        self.bot = None

    # when time call bot
    def is_call(
        self, 
        caller: Any, 
        ask_data
    ) -> bool:
        question = caller.bot_get_question(ask_data)
        if trigger in question:
            return True
        return False

    # get support model
    def get_models(
        self,
        caller: Any
    ) -> List[str]:
        return [self.type]

    # ask bot
    def ask(
        self, 
        caller: Any, 
        ask_data
    ) -> Generator[dict, None, None]:
        question = caller.bot_get_question(ask_data)
        yield caller.bot_set_response(code=1, message="o")
        yield caller.bot_set_response(code=0, message="ok.")
        # if error, then: yield caller.bot_set_response(code=-1, message="err")

    # exit bot
    def when_exit(
        self, 
        caller: Any
    ):
        pass

    # init bot
    def when_init(
        self, 
        caller: Any
    ):
        pass

    # no need define plugin_prefix
    plugin_prefix = 'bot_'

    # no need define bot_get_question
    def bot_get_question(
        self, 
        ask_data
    ):
        return ask_data['question']

    # no need define bot_get_preset
    def bot_get_preset(
        self, 
        ask_data
    ):
        return ask_data['preset']
    
    def bot_get_history(
        self,
        ask_data
    ):
        return ask_data['history']

    # no need define bot_set_response
    def bot_set_response(
        self, 
        code: int, 
        message: str
    ) -> Any:
        return {"code": code, "message": message}

    def bot_load_setting(
        self, 
        type: str
    ):
        return config.load_setting(type)
    
    def bot_log_dbg(
        self, 
        msg: str
    ):
        return log_dbg(msg, is_plugin=True)

    def bot_log_err(
        self, 
        msg: str
    ):
        return log_err(msg, is_plugin=True)

    def bot_log_info(
        self, 
        msg: str
    ):
        return log_info(msg, is_plugin=True)

class AimiPlugin:
    bots: Dict = {}
    bots_type: List[str] = []
    bot_obj: Bot = Bot()
    plugin_path = './aimi_plugin'
    
    def __init__(
        self
    ):
        self.__load_setting()

        self.__load_bot()
        
        self.when_init()

    def __load_setting(
        self
    ):
        try:
            setting = config.load_setting('aimi')
        except Exception as e:
            log_err(f'fail to load {self.type}: {e}')
            setting = {}
            return
        
        try:
            self.plugin_path = setting['plugin_path']
        except Exception as e:
            log_err(f'fail to get plugin_path: {e}')
            self.plugin_path = './aimi_plugin'

    def __load_bot(
        self
    ):
        # 遍历目录中的文件
        for filename in os.listdir(self.plugin_path):
            # skip example 
            if self.bot_obj.plugin_prefix + 'example.py' == filename:
                continue
                
            # 如果文件名以指定前缀开头并且是 Python 脚本
            if filename.startswith(self.bot_obj.plugin_prefix) and filename.endswith('.py'):
                # 使用 importlib 加载模块
                module_name = filename[:-3]  # 去掉 .py 后缀
                module_path = os.path.join(self.plugin_path, filename)
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                log_dbg(f'check file:{filename} ')
                
                # 实例化模块中的类
                if hasattr(module, 'Bot'):
                    try:
                        bot = module.Bot()
                        bot_type = bot.type
                        if bot_type in self.bots:
                            raise Exception(f'{bot_type} has in bots')
                        self.bots[bot_type] = bot
                        log_info(f'add plugin bot_type:{bot_type} bot:{module_name}')
                    except Exception as e:
                        log_err(f'fail to add plugin bot: {e}')
                        
    def bot_has_type(
        self, 
        type
    ) -> bool:
        if not len(self.bots):
            return False
        
        for bot_type, bot in self.bots.items():
            try:
                if bot_type == type:
                    return True
            except Exception as e:
                log_err(f'fail to check type bot: {bot_type} err: {e}')
        
        return False
    
    def bot_get_models(
        self
    ) -> Dict[str, List[str]]:
        if not len(self.bots):
            return {}
        
        bot_models = {}

        for bot_type, bot in self.bots.items():
            try:
                bot_models[bot_type] =  bot.get_models(self.bot_obj)
            except Exception as e:
                log_err(f'fail to get bot models type: {bot_type} err: {e}')

        return bot_models

    def bot_is_call(
        self, 
        question: str
    ) -> bool:
        if not len(self.bots):
            return False
        
        ask_data = {"question": question}
        
        for bot_type, bot in self.bots.items():
            try:
                if bot.is_call(self.bot_obj, ask_data):
                    return True
            except Exception as e:
                log_err(f'fail to check call bot: {bot_type} err: {e}')

        return False

    def bot_get_call_type(
        self, 
        question: Any
    ):
        if not len(self.bots):
            return None

        ask_data = {"question": question}

        for bot_type, bot in self.bots.items():
            try:
                if bot.is_call(self.bot_obj, ask_data):
                    return bot_type
            except Exception as e:
                log_err(f'fail to get bot call type: {bot_type} err: {e}')
                

        return None

    def bot_ask(
        self, 
        bot_ask_type: str, 
        question: str, 
        preset: str = "", 
        history: List[Dict] = [],
        timeout: int = 60
    ) -> Generator[dict, None, None]:
        if not len(self.bots):
            yield {
                message: "no bot",
                code: -1
            }
            return

        ask_data = {
            "question": question,
            "preset": preset,
            "history": history,
        }

        for bot_type, bot in self.bots.items():
            try:
                if bot_ask_type == bot_type:
                    yield from bot.ask(self.bot_obj, ask_data, timeout)
                    break
            except Exception as e:
                log_err(f'fail to ask bot: {e}')

    def when_exit(
        self
    ):
        if not len(self.bots):
            return 
        
        for bot_type, bot in self.bots.items():
            try:
                bot.when_exit(self.bot_obj)
            except Exception as e:
                log_err(f'fail to exit bot: {bot_type} err: {e}')

    def when_init(
        self
    ):
        if not len(self.bots):
            return
        
        for bot_type, bot in self.bots.items():
            try:
                bot.when_init(self.bot_obj)
            except Exception as e:
                log_err(f'fail to init bot: {bot_type} err: {e}')
    


aimi_plugin = AimiPlugin()
