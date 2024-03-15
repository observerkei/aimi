import atexit
import signal
import threading
import time
import random
import unicodedata
from typing import Generator, List, Dict, Any, Tuple
from contextlib import suppress

from tool.config import Config
from tool.util import log_dbg, log_err, log_info, make_context_messages
from core.aimi_plugin import Bot, ChatBot, ChatBotType, BotAskData
from app.app_qq import AppQQ
from app.app_web import AppWEB

from tool.md2img import Md
from core.memory import Memory
from core.session import Session


class ReplyStep:
    class TalkList:
        has_start: bool = False
        now_list_line_cnt: int = 0
        list_line_cnt_max: int = 0
        now_list_id: int = 0
        cul_line_cnt_max: bool = True

        def check_talk_list(self, line: str) -> bool:
            if self.now_list_line_cnt < self.list_line_cnt_max:
                self.now_list_line_cnt += 1
                return True

            # 刚好下一个下标过来了
            next_list_id_str = "{}. ".format(self.now_list_id + 1)
            next_list_id_ch_str = "{}。 ".format(self.now_list_id + 1)
            next_list_id_bing_str = "[{}]: ".format(self.now_list_id + 1)
            if (
                (next_list_id_str in line)
                or (next_list_id_ch_str in line)
                or (next_list_id_bing_str in line)
            ):
                log_dbg("check talk list[{}]".format(self.now_list_id))
                self.now_list_line_cnt = 0
                self.now_list_id += 1
                return True

            return False

        def reset(self):
            self.has_start = False
            self.now_list_line_cnt = 0
            self.list_line_cnt_max = 0
            self.now_list_id = 0
            self.cul_line_cnt_max = True

        def is_talk_list(self, line: str):
            # 有找到开始的序号
            if (not self.has_start) and (
                ("1. " in line) or ("1。 " in line) or ("[1]: " in line)
            ):
                self.has_start = True
                self.now_list_line_cnt = 1
                self.list_line_cnt_max = 1
                self.now_list_id = 1
                return True

            # 标记过才处理
            if not self.has_start:
                return False

            if "\n" == line:
                return True

            # 已经找到当前每行的长度
            if not self.cul_line_cnt_max:
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            if (self.now_list_id) and (
                ("2. " in line) or ("2。 " in line) or ("[2]: " in line)
            ):
                self.now_list_id = 2
                self.now_list_line_cnt = 0
                self.cul_line_cnt_max = False
                ret = self.check_talk_list(line)
                if not ret:
                    self.reset()
                return ret

            # 统计每块最大行
            self.list_line_cnt_max += 1
            return True

    class MathList:
        has_start: bool = False

        def __is_math_format(self, md: Md, line: str) -> bool:
            if "=" in line:
                return True
            if md.has_latex(line):
                log_dbg("match: is latex")
                return True
            if md.has_html(line):
                log_dbg("match: is html")
                return True
            return False

        def is_math_list(self, md: Md, line: str) -> bool:
            if self.__is_math_format(md, line):
                self.has_start = True
                return True

            if not self.has_start:
                return False

            if "\n" == line:
                return True

            self.has_start = False
            return False


class Aimi:
    type: str = "Aimi"
    timeout: int = 360
    master_name: str = ""
    setting: Dict = {}
    aimi_name: str = "Aimi"
    preset_facts: Dict[str, str] = {}
    max_link_think: int = 1024
    running: bool = True
    api: List[str] = []
    bot_path: str
    config: Config
    md: Md
    memory: Memory
    task_setting: Dict = {}
    app_web: AppWEB
    app_qq: AppQQ
    __session: Session
    __session_setting: Dict
    previous_api_type: str
    run_path: str

    @property
    def session(self):
        return self.__session
    
    def __init__(self):
        self.__load_setting()
        self.config = Config()
        self.md = Md(self.run_path)
        self.memory = Memory()

        self.__session = Session(self.__session_setting)

        self.app_web = AppWEB(
            session=self.session, 
            ask=self.web_ask, 
            get_all_models=self.get_all_models)

        self.app_qq = AppQQ()

        # 注册意外退出保护记忆
        atexit.register(self.__when_exit)
        signal.signal(signal.SIGTERM, self.__signal_exit)
        signal.signal(signal.SIGINT, self.__signal_exit)

    def run(self):
        self.notify_online()

        aimi_read = threading.Thread(target=self.read)
        app_qq_server = threading.Thread(target=self.app_qq.server)
        app_web_server = threading.Thread(target=self.app_web.server)
        aimi_dream = threading.Thread(target=self.memory.dream)

        # 同时退出
        aimi_read.setDaemon(True)
        aimi_dream.setDaemon(True)
        app_qq_server.setDaemon(True)
        app_web_server.setDaemon(True)

        aimi_read.start()
        aimi_dream.start()
        app_qq_server.start()
        app_web_server.start()

        cnt = 0
        while self.running:
            cnt = cnt + 1
            if cnt < 60:
                time.sleep(1)
                continue
            else:
                cnt = 0

            try:
                if not self.memory.save_memory():
                    log_err("save memory failed")

            except Exception as e:
                log_err(f"fail to save: " + str(e))

        log_dbg("aimi exit")

    def __get_api_type_by_question(self, session_id: str, question: str) -> str:
        chatbot = self.session.get_chatbot(session_id)
        if not chatbot:
            log_err(f"Session id failed: {session_id}")
            return ""
        
        for bot_type, bot in chatbot.each_bot():
            if not bot.init:
                continue

            ask_data = BotAskData(question=question)
            if bot.is_call(chatbot.bot_caller, ask_data):
                return bot_type

        # 一个都找不到，用之前的
        previous_api_type = self.session.get_previous_api_type(session_id)
        if previous_api_type and len(previous_api_type):
            return previous_api_type
        
        # 之前没有, 随机取一个, 优先取 task
        if chatbot.has_bot_init(ChatBotType.Task):
            return ChatBotType.Task
        
        for bot_type, bot in chatbot.each_bot():
            if not bot.init:
                continue
            return bot_type

        return ""

    @property
    def __busy_reply(self) -> str:
        busy = [
            "让我想想...",
            "......",
            "那个...",
            "这个...",
            "?",
            "喵喵喵？",
            "*和未知敌人战斗中*",
            "*大脑宕机*",
            "*大脑停止响应*",
            "*尝试构造语言中*",
            "*被神秘射线击中,尝试恢复中*",
            "*猫猫叹气*",
        ]
        return random.choice(busy)

    def read(self):
        while self.running:
            if not self.app_qq.has_message():
                time.sleep(1)
                continue

            for msg in self.app_qq:
                log_info("recv msg, try analyse")
                nickname = self.app_qq.get_name(msg)
                question = self.app_qq.get_question(msg)
                log_info("{}: {}".format(nickname, question))


                reply = ""
                reply_line = ""
                reply_div = ""
                answer = {}

                talk_list = ReplyStep.TalkList()
                math_list = ReplyStep.MathList()
                
                ask_data = BotAskData(question=question, nickname=nickname, aimi_name=self.aimi_name)
                session_id = self.session.create_session_id(self.aimi_name)
                if not self.session.has_session(session_id):
                    session_id = self.session.new_session(self.aimi_name, self.session.setting)
                    if not session_id:
                        log_err(f"fail to get new session_id.")
                        break
                log_dbg(f"sesion_id: {session_id}")

                api_type = self.__get_api_type_by_question(session_id, question)
                self.session.set_previous_api_type(session_id, api_type)

                code = 0
                for answer in self.ask(session_id, ask_data):
                    code = answer["code"]

                    message = answer["message"][len(reply) :]
                    reply_line += message

                    reply = answer["message"]

                    reply_div_len = len(reply_div)
                    log_dbg(
                        f"code: {str(code)} div: {str(reply_div_len)} line: {str(reply_line)}"
                    )

                    if code == 0 and (
                        len(reply_div) or ((not len(reply_div)) and len(reply_line))
                    ):
                        reply_div += reply_line
                        reply_line = ""

                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg(f"send div: {str(reply_div)}")

                        # 删除头尾换行符. 因为QQ不需要.
                        reply_div = unicodedata.normalize("NFKC", reply_div).strip()
                        # 有消息才需要发送.
                        if not reply_div.isspace():
                            self.app_qq.reply_question(msg, reply_div)

                        break
                    if (code == -1) and (len(reply_div) or len(reply_line)):
                        if not len(reply_div):
                            reply_div = self.__busy_reply
                        reply_div = self.reply_adjust(reply_div, api_type)
                        log_dbg(f"fail: {str(reply_line)}, send div: {str(reply_div)}")
                        
                        # 删除头尾换行符. 因为QQ不需要.
                        reply_div = unicodedata.normalize("NFKC", reply_div).strip()
                        # 有消息才需要发送.
                        if not reply_div.isspace():
                            self.app_qq.reply_question(msg, reply_div)
                        reply_line = ""
                        reply_div = ""
                        continue

                    if code != 1:
                        continue

                    if "\n" in reply_line:
                        if talk_list.is_talk_list(reply_line):
                            reply_div += reply_line
                            reply_line = ""
                            continue
                        elif math_list.is_math_list(self.md, reply_line):
                            reply_div += reply_line
                            reply_line = ""
                            continue
                        elif not len(reply_div):
                            # first line.
                            reply_div += reply_line
                            reply_line = ""

                        reply_div = self.reply_adjust(reply_div, api_type)

                        log_dbg("send div: " + str(reply_div))
                        
                        # 删除头尾换行符. 因为QQ不需要.
                        reply_div = unicodedata.normalize("NFKC", reply_div).strip()
                        # 有消息才需要发送.
                        if not reply_div.isspace():
                            self.app_qq.reply_question(msg, reply_div)

                        # 把满足规则的先发送，然后再保存新的行。
                        reply_div = reply_line
                        reply_line = ""

                log_dbg(f"answer: {str(type(answer))} {str(answer)}")
                reply = self.reply_adjust(reply, api_type)
                log_dbg(f"adjust: {str(reply)}")

                log_info(f"{nickname}: {question}")
                log_info(f"{self.aimi_name}: {str(reply)}")

                if code == 0:
                    pass  # self.app_qq.reply_question(msg, reply)

                # server failed
                if code == -1:
                    meme_err = self.config.meme.error
                    img_meme_err = self.app_qq.get_image_message(meme_err)
                    self.app_qq.reply_question(msg, "server unknow error :(")
                    self.app_qq.reply_question(msg, img_meme_err)

                # trans text to img
                if self.md.need_set_img(reply):
                    log_info("msg need set img")
                    img_file = self.md.message_to_img(reply)
                    cq_img = self.app_qq.get_image_message(img_file)

                    self.app_qq.reply_question(msg, cq_img)

    def reply_adjust(self, reply: str, res_api: str) -> str:
        if res_api == ChatBotType.Bing:
            reply = reply.replace("必应", f" {self.aimi_name}通过必应得知: ")
            reply = reply.replace("你好", " Master你好 ")
            reply = reply.replace("您好", " Master您好 ")

        return reply

    def web_ask(
        self,
        session_id: str,
        question: str,
        nickname: str = None,
        model: str = "auto",
        api_key: str = "",
        owned_by: str = "Aimi",
        context_messages: Any = None,
    ) -> Generator[dict, None, None]:
        try:

            preset = context_messages[0]["content"]
            api_type = owned_by

            if api_type == self.aimi_name and ChatBotType.Task in model:
                api_type = ChatBotType.Task

            nickname = nickname if nickname and len(nickname) else self.master_name

            talk_history = context_messages[1:-1]

            ask_data = BotAskData(
                question=question,
                model=model,
                aimi_name=self.aimi_name,
                preset=preset,
                nickname=nickname,
                messages=context_messages,
                conversation_id=self.memory.openai_conversation_id,
            )

            if (api_type == self.aimi_name):
                yield from self.ask(session_id, ask_data)
            else:
                talk_history = context_messages[1:-1]
                ask_data.history = self.memory.make_history(talk_history)
                yield from self.__post_question(
                    session_id=session_id,
                    api_type=api_type,
                    ask_data=ask_data,
                )
        except Exception as e:
            log_err(f"fail to ask: {e}")
            yield f"Error: {e}"

    def ask(
        self, session_id: str, ask_data: BotAskData
    ) -> Generator[dict, None, None]:
        try:
            question = ask_data.question
            api_type = self.__get_api_type_by_question(session_id, question)
            self.session.set_previous_api_type(session_id, api_type)
            preset = ask_data.preset
            
            if preset.isspace():
                with suppress(KeyError):
                    preset = self.preset_facts[api_type]

            talk_history = self.memory.search(question, self.max_link_think)
            ask_data.messages = make_context_messages(question, preset, talk_history)

            history = self.memory.make_history(talk_history)
            ask_data.history = history

            for message in self.__post_question(
                session_id=session_id,
                api_type=api_type,
                ask_data=ask_data,
            ):
                if not message:
                    continue
                # log_dbg(f'message: {str(type(message))} {str(message)} answer: {str(type(answer))} {str(answer))}'

                # save self.memory
                if message["code"] == 0:
                    self.memory.append(q=question, a=message["message"])

                yield message
        except Exception as e:
            log_err(f"fail to ask: {e}")
            yield f"Error: {e}"

    def __post_question(
        self, session_id: str, api_type: str, ask_data: BotAskData
    ) -> Generator[dict, None, None]:
        log_dbg("use api: " + str(api_type))

        chatbot = self.session.get_chatbot(session_id)
        if not chatbot:
            log_err(f"no chatbot, session_id failed: {session_id}.")
        else:
            if api_type == ChatBotType.OpenAI:
                yield from self.__post_openai(chatbot, ask_data)
            elif chatbot.has_type(api_type):
                yield from chatbot.ask(api_type, ask_data)
            else:
                log_err("not suppurt api_type: " + str(api_type))

    def __post_openai(self, chatbot: ChatBot, ask_data: BotAskData) -> Generator[dict, None, None]:

        answer = chatbot.ask(ChatBotType.OpenAI, ask_data)
        # get yield last val
        for message in answer:
            # log_dbg('now msg: ' + str(message))

            try:
                if (
                    message
                    and message["code"] == 0
                    and message["conversation_id"]
                    and message["conversation_id"] != self.memory.openai_conversation_id
                ):
                    self.memory.openai_conversation_id = message["conversation_id"]
                    log_info(
                        "set new con_id: " + str(self.memory.openai_conversation_id)
                    )
            except Exception as e:
                log_dbg(f"no conv_id")

            yield message
    
    def get_all_models(self, session_id: str) -> Dict[str, List[str]]:
        try:
            if not self.session.has_session(session_id):
               raise Exception(f"no session.")
            
            chatbot = self.session.get_chatbot(session_id)
            if not chatbot:
                raise Exception(f"session_id failed, no chatbot, {session_id}")

            bot_models: Dict[str, List[str]] = {}

            aimi_models: List = []
            for bot_type, bot in chatbot.each_bot():
                if not bot.init:
                    continue
                aimi_models.append("auto")
                break

            # 放前面
            if chatbot.has_bot_init(ChatBotType.Task):
                for m in chatbot.get_bot_models(ChatBotType.Task):
                    aimi_models.append(m)

            if len(aimi_models):
                bot_models[self.aimi_name] = aimi_models

            for bot_type, bot in chatbot.each_bot():
                if not bot.init:
                    continue
                if ChatBotType.Task == bot_type:
                    continue
                models = bot.get_models(chatbot.bot_caller)
                bot_models[bot_type] = models

            return bot_models
        except Exception as e:
            log_err(f"fail to get all models: {e}")
            return {}

    def __load_setting(self):
        try:
            setting = Config.load_setting("aimi")
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return
        self.setting = setting

        try:
            self.aimi_name = setting["name"]
        except Exception as e:
            log_err(f"fail to load aimi: {e}")
            self.aimi_name = "Aimi"

        try:
            self.task_setting = setting["task"]
        except Exception as e:
            log_err(f"fail to load aimi: {e}")
            self.task_setting = {}

        try:
            self.master_name = setting["master_name"]
        except Exception as e:
            log_err(f"fail to load aimi: {e}")
            self.master_name = ""

        try:
            self.bot_path = setting["bot_path"]
        except Exception as e:
            log_err(f"fail to load aimi bot_path: {str(e)}")
            self.bot_path = './aimi_plugin/bot'

        try:
            self.run_path = setting["run_path"]
        except Exception as e:
            log_err(f"fail to load aimi run_path: {str(e)}")
            self.run_path = "./run"

        try:
            self.preset_facts = {}
            preset_facts_setting: Dict[str, List[str]] = setting["preset_facts"]
            
            for api_type, preset_facts in preset_facts_setting.items():
                fill_preset_facts = ""
                count = 0
                for fact in preset_facts:
                    fact = fact.replace("<name>", self.aimi_name)
                    fact = fact.replace("<master>", self.master_name)
                    count += 1
                    if count != len(preset_facts):
                        fact += "\n"
                    fill_preset_facts += fact
                self.preset_facts[api_type] = fill_preset_facts
                
            self.preset_facts["default"] = self.preset_facts[ChatBotType.OpenAI]
        except Exception as e:
            log_err(f"fail to load aimi preset: " + str(e))
            self.preset_facts = {}

        try:
            self.__session_setting = ChatBot.load_bot_setting(self.bot_path)
            self.__session_setting[ChatBotType.Task] = self.task_setting
            self.__session_setting['bot_path'] = self.bot_path
        except Exception as e:
            log_err(f"fail to load default chatbot settings: {str(e)}")
            self.__session_setting = {}

    def notify_online(self):
        if not self.app_qq.is_online():
            log_dbg(f"{self.app_qq.type} offline")
            return
        self.app_qq.reply_online()

    def notify_offline(self):
        self.app_qq.reply_offline()

    def __signal_exit(self, sig, e):
        log_info("recv exit sig.")
        self.running = False
        self.app_qq.stop()

    def __when_exit(self):
        self.running = False

        log_info("now exit aimi.")
        self.notify_offline()

        if self.memory.save_memory():
            log_info("exit: save self.memory done.")
        else:
            log_err("exit: fail to save self.memory.")

        try:
            self.session.when_exit()
        except Exception as e:
            log_err(f"fail to exit aimi chatbot: {e}")
