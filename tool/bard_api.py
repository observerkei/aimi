import os
import time
from typing import Generator, List, Any
from contextlib import suppress
import pprint
import google.generativeai as palm

from tool.util import log_dbg, log_err, log_info
from tool.config import Config


class BardAPI:
    type: str = "bard"
    chatbot: Any
    cookie_key: str = ""
    max_requestion: int = 1024
    max_repeat_times: int = 3
    trigger: List[str] = []
    init: bool = False
    use_web_ask: bool = False
    models: List[str] = []

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
        if self.use_web_ask:
            yield from self.web_ask(question, timeout)
        else:
            yield from self.api_ask(question, timeout)

    def api_ask(
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

                calc_prompt = f"""
Please solve the following problem.

{question}

----------------

Important: Use the calculator for each step.
Don't do the arithmetic in your head. 

To use the calculator wrap an equation in <calc> tags like this: 

<calc> 3 cats * 2 hats/cat </calc> = 6

----------------

"""
                equation = None
                while equation is None:
                    completion = self.chatbot.generate_text(
                        model=self.models[0],
                        prompt=calc_prompt,
                        stop_sequences=["</calc>"],
                        # The maximum length of the response
                        max_output_tokens=800,
                    )

                    try:
                        answer["message"], equation = completion.result.split(
                            "<calc>", maxsplit=1
                        )
                        res = answer["message"]
                        log_dbg(f"{str(res)}")
                    
                        yield answer

                    except Exception:
                        continue
                
                answer['code'] = 0
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

        api_key = self.api_key
        if api_key and len(api_key):
            try:
                self.chatbot = palm
                self.chatbot.configure(api_key=api_key)
                models = [
                    m
                    for m in self.chatbot.list_models()
                    if "generateText" in m.supported_generation_methods
                ]
                self.models = [m.name for m in models]
                log_dbg(str(self.models))
                self.init = True
                self.use_web_ask = False
                return 0
            except Exception as e:
                log_err(f"fail to create bard: {e}")
                return -1
        cookie_key = self.cookie_key
        if (cookie_key) and (len(cookie_key)):
            from Bard import Chatbot

            try:
                new_bot = Chatbot(cookie_key)
                self.chatbot = new_bot
                self.init = True
                self.use_web_ask = True
                log_info(f"create {self.type} done")
                return 0
            except Exception as e:
                log_err(f"fail to create bard: {e}")
                return -1

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
            self.api_key = setting["api_key"]
        except Exception as e:
            log_err("fail to load bard config: " + str(e))
            self.api_key = ""
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
