import asyncio
from EdgeGPT import Chatbot, ConversationStyle
from contextlib import suppress
from typing import Generator, List
import time

from tool.util import log_dbg, log_err, log_info
from tool.config import config

class BingAPI:
    chatbot: Chatbot
    use_web_ask: bool = True
    max_requestion: int = 1024
    max_repeat_times: int = 3
    type: str = 'bing'
    cookie_path: str = ''
    wss_link: str = ''
    countdown: List[str] = [
        '?', 
        'I',     'II',   'III',   'IV',  'V',
        'VI',   'VII',  'VIII',  'VIV',  'X',
        'XI',   'XII',  'XIII',  'XIV', 'XV',
        'XVI', 'XVII', 'XVIII', 'XVIV', 'XX'
    ]

    def ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        async def fuck_async(question: str, timeout: int = 360) -> Generator[dict, None, None]:
            result: dict = {}
            async for res in self.web_ask(question, timeout):
                log_dbg('out: ' + str(type(result)) + ' val: ' + str(res))
                result = res
            return result
        
        if self.use_web_ask:
            result = asyncio.run(fuck_async(question, timeout))
            log_dbg('res: ' + str(type(result)) + ' val: ' + str(result))
            yield result

            
    async def web_ask(
        self,
        question: str,
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = { 
           "message": '',
           "code": 1
        }

        req_cnt = 0
        
        while req_cnt < self.max_repeat_times:
            req_cnt += 1
            
            try:
                log_dbg('try ask: ' + str(question))

                async for final, response in self.chatbot.ask_stream(
                    prompt = question, 
                    conversation_style = ConversationStyle.creative,
                    wss_link = self.wss_link
                ):
                    if not response:
                        continue
                    if not final:
                        answer['message'] = response
                        yield answer
                        continue
                    
                    cur_messages = 0
                    max_messages = 0
                    with suppress(KeyError):
                        cur_messages = response["item"]["throttling"]["numUserMessagesInConversation"]
                        max_messages = response["item"]["throttling"]["maxNumUserMessagesInConversation"]

                        if cur_messages == max_messages:
                            asyncio.run(self.__bot_create())
                        
                    raw_text = ''
                    with suppress(KeyError):
                        raw_text = response["item"]["messages"][1]["adaptiveCards"][0]["body"][0]["text"]

                    cd_idx = 1 + max_messages - cur_messages 
                    res_all = raw_text + '\n' + '[{}]'.format(self.countdown[cd_idx])

                    answer['message'] = res_all

                answer['code'] = 0
                yield answer
             
            except Exception as e:
                log_err('fail to ask: ' + str(e))
                log_info('server fail, sleep 15')
                time.sleep(15)

                await self.__bot_reload()
                
                answer['message'] = str(e)
                answer['code'] = -1
                yield answer

            # request complate.
            if answer['code'] == 0:
                break

    def __init__(self) -> None:

        self.__load_setting()
        
        asyncio.run(self.__bot_create())
        
    async def __bot_create(self):
        self.chatbot = await Chatbot.create(None, None, self.cookie_path)
        self.use_web_ask = True
    
    async def __bot_reload(self):
        log_dbg('try reload chatbing bot')
        try:
            await self.chatbot.close()
        except:
            log_err('fail to close edge')

        log_info('create new edge.')
        await self.__bot_create()
        
    def __load_setting(self):
        try:
            self.max_requestion = config.setting['bing']['max_requestion']
        except Exception as e:
            log_err('fail to load chatbing config: ' + str(e))
            self.max_requestion = 512
        try:
            self.max_repeat_times = config.setting['bing']['max_repeat_times']
        except Exception as e:
            log_err('fail to load chatbing config: ' + str(e))
            self.max_repeat_times = 3
        try:
            self.cookie_path = config.setting['bing']['cookie_path']
            self.use_web_ask = True
        except Exception as e:
            log_err('fail to load chatbing config: ' + str(e))
            self.cookie_path = ''

        try:
            self.wss_link = config.setting['bing']['wss_link']
        except Exception as e:
            log_err('fail to load chatbing config: ' + str(e))
            self.wss_link = ''

bing_api = BingAPI()
