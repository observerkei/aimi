import wolframalpha
import time
import re
from typing import List, Any, Generator
import json

from tool.config import config
from tool.util import log_dbg, log_info, log_err

class WolframAPI:
    type: str = 'wolfram'
    client: Any
    app_id: str = ''
    trigger: List[str] = []
    max_repeat_times: int = 1
    init: bool = False

    def __init__(self):
        self.__load_setting()
        if not self.app_id or not (len(self.app_id)):
            log_info('no wolfram app id')
            return
        try:
            self.client = wolframalpha.Client(self.app_id)
            self.init = True
        except Exception as e:
            log_err(f"fail to init wolfram: {e}")
    
    def __load_setting(self):
        setting = {}
        try:
            setting = config.load_setting('wolfram')
        except Exception as e:
            log_err(f"fail to load wolfram setting: {e}")
        
        try:
            self.app_id = setting["app_id"]
        except Exception as e:
            log_err(f"fail to load wolfram: {e}")
            self.app_id = ''
        
        try:
            self.trigger = setting['trigger']
        except Exception as e:
            log_err('fail to load wolfram config: ' + str(e))
            self.trigger = ['@wolfram', '#wolfram' ]

        try:
            self.max_repeat_times = setting['max_repeat_times']
        except Exception as e:
            log_err('fail to load wolfram config: ' + str(e))
            self.max_repeat_times = 1

    def is_call(self, question) -> bool:
        for call in self.trigger:
            if call.lower() in question.lower():
                return True
        
        return False

    def get_sub_from_context(self, context, title):
        log_dbg(f"type: {str(type(context))}")

    
        for pod in context.pods:
            if not pod:
                continue
            try:
                if not pod.subpods:
                    continue
            except Exception as e:
                log_dbg(f"no subpods: {e}")
                continue

            for sub in pod.subpods:
                if not sub:
                    continue
                sub_title = ''
                try:
                    sub_title = sub.title
                except Exception as e:
                    log_dbg(f"no title: {e}")
                    continue

                log_dbg(f"sub title: {str(sub.title)}")
                if title.lower() in sub.title.lower():
                    return sub
        return None

    def get_cq_image(self, context) -> str:
        res_img = ''
        try:
            for pod in context.pods:
                pod_title = ''

                try:
                    if not pod.subpods:
                        continue
                    pod_title = pod.title
                except Exception as e:
                    log_dbg(f"no subpods: {e}")
                    continue

                for sub in pod.subpods:
                    img_url = ''
                    try:
                        img_url = sub.img.src
                    except:
                        continue

                    cq_image = f'{pod_title}\n[CQ:image,file={img_url}]\n\n'
                    res_img += cq_image

        except Exception as e:
            log_err(f"fail to get img: {e}")
        
        return res_img
    
    def get_plaintext(self, context) -> str:
        plaintext = ''
        try:
            line = 0
            for pod in context.pods:
                line += 1
                if line != 2: 
                    continue

                try:
                    if not pod.subpods:
                        continue
                except Exception as e:
                    log_dbg(f"no subpods: {e}")
                    continue

                for sub in pod.subpods:
                    sub_t = ''
                    try:
                        sub_t = sub.plaintext
                        if not sub_t:
                            continue
                    except:
                        continue

                    plaintext += sub_t + "\n\n"

            if (
                not plaintext or 
                not len(plaintext) or
                not ('=' in plaintext)
            ):
                sub = self.get_sub_from_context(context, "Possible intermediate steps")
                #plaintext = "Possible intermediate steps:\n" + sub.plaintext
                plaintext = sub.plaintext

                raise Exception(f"fail to get sub plaintext")
        except Exception as e:
            log_err(f"fail to get plaintext: {e}")
            log_dbg(f'res: {str(context)}')
        
        return plaintext

    def __del_trigger(self, question) -> str:
        sorted_list = sorted(self.trigger, reverse=True, key=len)
        for call in sorted_list:
            if call.lower() in question.lower():
                return re.sub(re.escape(call), '', question, flags=re.IGNORECASE)

        return question

    def ask(self, question) -> Generator[dict, None, None]:
        answer = {
            "code": 1,
            "message": ''
        }
        
        if not self.init:
            answer['code'] = -1
            yield answer
            return
        
        question = self.__del_trigger(question)

        params = (
            ('podstate', 'Step-by-step solution'),
        )

        req_cnt = 0

        while req_cnt < self.max_repeat_times:
            req_cnt += 1

            answer['code'] = 1

            try:
                log_dbg(f'try ask: {question}')
                res = self.client.query(question, params)

                plaintext = self.get_plaintext(res)
                cq_image = self.get_cq_image(res)

                message = plaintext
                if (not message 
                    or len(message) < 5
                    or 'step-by-step solution unavailable' in str(message) 
                    or not ("=" in message)
                ):
                    message = str(res)
                    answer['message'] = message
                    log_dbg(f'msg fail, res html.')
                    yield answer

                answer['message'] = message
                answer['code'] = 0

                yield answer
                break

            except Exception as e:
                log_err(f'fail to query wolfram: {e}')
                answer['code'] = -1
                yield answer
                continue

        """
        answer['code'] = 0
        answer['message'] = str(res)
        yield answer
        return
        """

        """
        message = ''
        for line in plaintext.splitlines():
            line += '\n'
            message += line
            answer['message'] = message
            yield answer
            time.sleep(0.5)

        message += ' \n'
        answer['message'] = message
        yield answer
        """

        """
        for img in cq_image.splitlines():
            img += '\n'
            message += img
            answer['message'] = message
            yield answer
            time.sleep(0.5)
        """

        #answer['message'] += cq_image

wolfram_api = WolframAPI()
