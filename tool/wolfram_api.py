import wolframalpha
import re
from typing import List, Any, Generator

from tool.config import config
from tool.util import log_dbg, log_info, log_err

class WolframAPI:
    type: str = 'wolfram'
    client: Any
    app_id: str = ''
    trigger: List[str] = []
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

    def is_call(self, question) -> bool:
        for call in self.trigger:
            if call.lower() in question.lower():
                return True
        
        return False

    def get_sub_from_context(self, context, title):
      for pod in context.pods:
        if not pod:
            continue
        if not pod.subpods:
            continue
        for sub in pod.subpods:
            if not sub:
                continue
            if title == sub.title:
                return sub
        return None

    def get_cq_image(self, context) -> str:
        img_url = ''
        try:
            sub = self.get_sub_from_context(context, "Possible intermediate steps")
            if not sub:
                raise Exception(f"fail to get sub as: Possible intermediate steps")
            img_url = sub.img.src
            if not img_url:
                raise Exception(f"fail to get sub img_url")
        except Exception as e:
            log_err(f"fail to get img: {e}")
        
        cq_image = f"[CQ:image,file={img_url}]"

        return cq_image
    
    def get_plaintext(self, context) -> str:
        plaintext = ''
        try:
            sub = self.get_sub_from_context(context, "Possible intermediate steps")
            if not sub:
                raise Exception(f"fail to get sub as: Possible intermediate steps")
            plaintext = sub.plaintext
            if not img_url:
                raise Exception(f"fail to get sub plaintext")
        except Exception as e:
            log_err(f"fail to get plaintext: {e}")
        
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

        ret = ''
        try:
            res = self.client.query(question, params)
        except Exception as e:
            log_err(f'fail to query wolfram: {e}')
            answer['code'] = -1
            yield answer
            return
        
        plaintext = self.get_plaintext(res)
        cq_image = self.get_cq_image(res)
        
        message = f"{plaintext}\n\n"
        answer['message'] = message
        yield answer

        message += cq_image
        answer['message'] = message
        answer['code'] = 0

        yield answer

wolfram_api = WolframAPI()