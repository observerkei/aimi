import os
import time
from typing import Generator, List
from Bard import Chatbot
from contextlib import suppress

from tool.util import log_dbg, log_err, log_info
from tool.config import Config


class BardAPI:
    type: str = "bard"
    chatbot: Chatbot
    cookie_key: str = ""
    max_requestion: int = 1024
    max_repeat_times: int = 3
    trigger: List[str] = []
    init: bool = False

    def is_call(self, question) -> bool:
        for call in self.trigger:
            if call.lower() in question.lower():
                return True
        return False

    def get_models(self) -> List[str]:
        if not self.init:
            return []

        return [f"Google {self.type}"]

    def ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        yield from self.web_ask(question, timeout)

    def web_ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = {"message": "", "code": 1}

        if (not self.init) and (self.__bot_create()):
            log_err("fail to create bard bot")
            answer["code"] = -1
            return answer

        req_cnt = 0

        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            answer["code"] = 1

            try:
                log_dbg("try ask: " + str(question))

                data = self.chatbot.ask(question)
                content = data["content"]
                message = content
                try:
                    choices = data["choices"]
                    choice1 = choices[0]["content"][0]
                    choice2 = choices[1]["content"][0]
                    choice3 = choices[2]["content"][0]
                    log_dbg(f"0. {content}\n1. {choice1}\n2. {choice2}\n3. {choice3}")
                    # message = choice3
                except Exception as e:
                    log_err(f"fail to get choice:{e}")

                """
                message = ''
                for line in content.splitlines():
                    line += '\n'
                    message += line
                    answer['message'] = message
                    yield answer
                    time.sleep(0.3)
                """

                answer["message"] = message
                log_dbg(f"recv bard: {str(answer['message'])}")

                answer["code"] = 0
                yield answer

            except Exception as e:
                log_err("fail to ask: " + str(e))
                log_info("server fail, maybe need check cookie, sleep 5")
                time.sleep(5)
                self.__bot_create()
                log_info("reload bot")

                answer["message"] = str(e)
                answer["code"] = -1
                yield answer

            # request complate.
            if answer["code"] == 0:
                break

    def __bot_create(self):
        self.init = False

        cookie_key = self.cookie_key
        if (not cookie_key) or (not len(cookie_key)):
            return -1
        try:
            new_bot = Chatbot(cookie_key)
            self.chatbot = new_bot
            self.init = True
            log_info(f"create {self.type} done")
        except Exception as e:
            log_err(f"fail to create bard: {e}")
            return -1
        return 0

    def __init__(self) -> None:
        self.__load_setting()

        try:
            self.__bot_create()
        except Exception as e:
            log_err("fail to init Bard: " + str(e))
            self.init = False

    def __load_setting(self):
        try:
            setting = Config.load_setting(self.type)
        except Exception as e:
            log_err(f"fail to load {self.type}: {e}")
            setting = {}
            return

        try:
            self.max_requestion = setting["max_requestion"]
        except Exception as e:
            log_err("fail to load bard config: " + str(e))
            self.max_requestion = 1024
        try:
            self.cookie_key = setting["cookie_1PSID"]
        except Exception as e:
            log_err("fail to load bard config: " + str(e))
            self.cookie_key = ""
        try:
            self.max_repeat_times = setting["max_repeat_times"]
        except Exception as e:
            log_err("fail to load bard config: " + str(e))
            self.max_repeat_times = 3
        try:
            self.trigger = setting["trigger"]
        except Exception as e:
            log_err("fail to load bard config: " + str(e))
            self.trigger = ["@bard", "#bard"]
