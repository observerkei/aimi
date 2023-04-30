from revChatGPT.V1 import Chatbot
from typing import Generator

from tool.util import log_dbg, log_err
from tool.config import config

class OpenAIAPI:
    chatbot: Chatbot
    use_web_ask: bool = True
    max_requestion: int = 1024
    access_token: str = ''

    class InputType:
        SYSTEM = 'system'
        USER = 'user'
        ASSISTANT = 'assistant'

    def ask(
        self,
        question: str,
        conversation_id: str = '',
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        if self.use_web_ask:
            yield from self.web_ask(question, conversation_id, timeout)
        else:
            yield from self.api_ask(question, conversation_id, timeout)
        
    def web_ask(
        self,
        question: str,
        conversation_id: str = '',
        timeout: int = 360,
    ) -> Generator[dict, None, None]:
        answer = { 
           "message": '',
           "conversation_id": conversation_id,
           "code": 1
        }
        
        try:
            log_dbg('try ask: ' + question)
            
            if len(conversation_id):
                for data in self.chatbot.ask(
                    question,
                    conversation_id
                ):
                    answer['message'] = data["message"]
                    yield answer
            else:
                for data in self.chatbot.ask(question):
                    answer['message'] = data["message"]
                    yield answer
                    
                answer['conversation_id'] = self.chatbot.get_conversations(0, 1);

            answer['code'] = 0
            yield answer
         
        except Exception as e:
            log_err('fail to ask: ' + str(e))

            answer['message'] = str(e)
            answer['code'] = -1
            yield answer

    def api_ask(
        self,
        question: str,
        conversation_id: str = '',
        timeout: int = 360,
    ) -> Generator[dict, None, None]:

        log_err('not support api!')
        
        yield {
           "message": 'not support api!',
           "conversation_id": conversation_id,
           "code": -1
        }
    
    # chatgpt输入
    def make_chatgpt_input_item(type: InputType, content: str) -> dict:
        return {'role': type, 'content': content}
    
    def __init__(self) -> None:

        self.__load_setting()
        
        access_token = self.access_token
        if len(access_token):
            self.chatbot = Chatbot({
                "access_token": access_token
            })
            self.use_web_ask = True

    def __load_setting(self):
        try:
            self.max_requestion = config.setting['openai_config']['max_requestion']
        except:
            self.max_requestion = 1024
        try:
            self.access_token = config.setting['openai_config']['access_token']
        except:
            self.access_token = ''
        

openai_api = OpenAIAPI()
