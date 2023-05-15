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

    def __init__(self):
        self.bot = None

    # when time call bot
    def is_call(self, caller: Any, ask_data) -> bool:
        question = caller.bot_get_question(ask_data)
        if trigger in question:
            return True
        return False

    # ask bot
    def ask(self, caller: Any, ask_data) -> Generator[dict, None, None]:
        question = caller.bot_get_question(ask_data)
        yield caller.bot_set_response(code=1, message="o")
        yield caller.bot_set_response(code=0, message="ok.")
        # if error, then: yield caller.bot_set_response(code=-1, message="err")

    # exit bot
    def when_exit(self):
        pass

    # init bot
    def when_init(self):
        pass

    # no need define plugin_prefix
    plugin_prefix = 'bot_'

    # no need define bot_get_question
    def bot_get_question(self, ask_data):
        return ask_data['question']

    # no need define bot_set_response
    def bot_set_response(self, code: int, message: str) -> Any:
        return {"code": code, "message": message}

class AimiPlugin:
    bots: Dict = {}
    bots_type: List[str] = []
    bot_obj: Bot = Bot()
    plugin_path = './aimi_plugin'
    

    def __init__(self):
        self.__load_setting()

        self.__load_bot()
        
        self.when_init()

    def __load_setting(self):
        try:
            self.plugin_path = config.setting['aimi']['plugin_path']
        except Exception as e:
            log_err(f'fail to get plugin_path: {e}')
            self.plugin_path = './aimi_plugin'

    def __load_bot(self):
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
                        type = bot.type
                        self.bots[type] = bot
                        log_info(f'add plugin bot:{module_name}')
                    except Exception as e:
                        log_err(f'fail to add plugin bot: {e}')
                        
    def bot_has_type(self, type) -> bool:
        if not len(self.bots):
            return False
        
        for bot_type, bot in self.bots.items():
            try:
                if bot_type == type:
                    return True
            except Exception as e:
                log_err(f'fail to check type bot: {bot_type} err: {e}')
        
        return False
        

    def bot_is_call(self, question: str) -> bool:
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

    def bot_get_call_type(self, question: Any):
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

    def bot_ask(self, bot_ask_type: str, question: str,  timeout: int = 60) -> Generator[dict, None, None]:
        if not len(self.bots):
            yield {
                message: "no bot",
                code: -1
            }
            return
        
        ask_data = {"question": question}

        for bot_type, bot in self.bots.items():
            try:
                if bot_ask_type == bot_type:
                    yield from bot.ask(self.bot_obj, ask_data, timeout)
                    break
            except Exception as e:
                log_err(f'fail to ask bot: {e}')

    def when_exit(self):
        if len(self.bots):
            for bot_type, bot in self.bots.items():
                try:
                    bot.when_exit()
                except Exception as e:
                    log_err(f'fail to exit bot: {bot_type} err: {e}')

    def when_init(self):
        if len(self.bots):
            for bot_type, bot in self.bots.items():
                try:
                    bot.when_init()
                except Exception as e:
                    log_err(f'fail to init bot: {bot_type} err: {e}')
    


aimi_plugin = AimiPlugin()
