import json
from typing import Dict, Any, List, Generator
from pydantic import BaseModel, constr

from tool.openai_api import openai_api
from tool.util import log_dbg, log_err, log_info, make_context_messages

class TaskStepItem(BaseModel):
    id: str
    step: str

class SyncToolItem(BaseModel):
    call: str
    execute: constr(regex='system|AI')
    description: str
    input: Any
    response: Any

class TaskRunningItem(BaseModel):
    call: str
    execute: str
    input: Any
    reasoning: str = None
    response: Any = None

class TaskItem(BaseModel):
    task_id: str
    task_info: str
    task_step: List[TaskStepItem]
    sync_tool: List[SyncToolItem]
    running: List[TaskRunningItem]

class Task():
    type: str = 'task'
    tasks: Dict[str, TaskItem]
    sync_tool: List[SyncToolItem]
    now_task_id: str
    aimi_name: str = 'Aimi'

    def task_response(
        self, 
        answer: str
    ) -> Generator[dict, None, None]:
        response = ''
        try:
            start_index = answer.find("[")
            if start_index != -1:
                end_index = answer.rfind("]\n```", start_index)
                if end_index != -1:
                    answer = answer[start_index:end_index+1]
                else:
                    end_index = answer.rfind("]", start_index)
                    if end_index != -1:
                        if ']' == answer[-1]:
                            # 防止越界
                            answer = answer[start_index:]
                        else:
                            answer = answer[start_index:end_index+1]
                        # 去除莫名其妙的解释说明

            data = json.loads(answer)
            tasks = [TaskRunningItem(**item) for item in data]
            running: List[TaskRunningItem] = []
            running_size: int = 0
            for task in tasks:
                try:
                    log_dbg(f"get task: {str(task)}")
                    if task.reasoning:
                        log_dbg(f"reasoning: {str(task.reasoning)}")
                    
                    if task.call == "chat":
                        role = task.input['role']
                        content = task.input['content']
                        response = self.chat(role, content)
                        yield response
                    elif task.call == 'find_task_step':
                        task_id: str = task.input['task_id']
                        default: List[TaskStepItem] = task.input['default']
                        step = self.find_task_step(task_id, default)
                        log_dbg(f"step: {str(step)}")
                    elif task.call == 'set_task_info':
                        task_id: str =  task.input['task_id']
                        task_info: str = task.input['task_info']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        self.set_task_info(task_id, task_info, task_step)
                        log_dbg(f"set task: {str(self)}")
                    elif task.call == 'critic':
                        self.critic(task.response)
                    else:
                        log_err(f'no suuport call: {str(self.call)}')
                        continue
                    if running_size < 512:
                        running.append(task)
                        running_size += len(str(task))
                except Exception as e:
                    log_err(f"fail to load task: {str(e)}")
            self.__append_running(running)
            log_dbg(f"update running success: {len(running)} : {str(running)}")
        except Exception as e:
            log_err(f"fail to load task res: {str(e)} : {str(answer)}")
        
        yield response

    def chat(
        self,
        role: str, 
        content: str
    ) -> str:
        if role != self.aimi_name:
            return ''
        
        return content
    
    def make_chat(
        self,
        question: str
    ) -> str:
        chat = TaskRunningItem(
            call='chat',
            execute='system',
            input={'role':'Master', 'content':question}
        )
        return str(chat)

    def find_task_step(
        self,
        task_id: str, 
        default: List[TaskStepItem]
    ):
        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            if task.task_step:
                return task.task_step
            task.task_step = default
            return task.task_step

    def set_task_info(
        self,
        task_id: str, 
        task_info: str, 
        task_step: List[TaskStepItem]
    ):
        for _, task in self.tasks.items():
            if task_id == task.task_id:
                task.task_info = task_info
                task.task_step = task_step
                return task
        task = TaskItem(
            task_id=task_id,
            task_info=task_info,
            task_step=task_step,
            running=[]
        )
        self.tasks[task_id] = task
        return task

    def critic(
        self,
        response
    ):
        try:
            if response['success'] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                if len(self.tasks) > 1:
                    del self.tasks[self.now_task_id]
                    log_info(f'task_info: {task_info}, delete.')
                
                    for _, task in self.tasks:
                        self.now_task_id = task.task_id
                        return
                else:
                    # 一个任务也没有了
                    self.tasks[self.now_task_id].task_info = '当前没有事情可以做, 找Master聊天吧...'
                    self.tasks[self.now_task_id].task_step = [] # 清空原有步骤 ...
                
        except Exception as e:
            log_err(f"fail to critic {str(response)} : {str(e)}")

    def __init__(self):
        try:
            self.__load_task()
        except Exception as e:
            log_err(f"fait to init: {str(e)}")
    
    def __load_task(self):
        self.sync_tool =  [
            {
                "call": "chat",
                "execute": "system",
                "description": "给某对象发送消息.你不能生成Master的话.如果running中最后一条是Master问的回答,你可以生成一条符合情景的Aimi的回答.",
                "input": {
                    "role": "是谁写的消息, 如果是你(Aimi),则只能填写: Aimi",
                    "content": "要说的内容."
                },
                "response": None
            },
            {
                "call": "find_task_step",
                "execute": "system",
                "description": "如果 task_step 为空,则需要查找一下.",
                "input": {
                    "task_id": "需要查找的task 对应的 id",
                    "default": [
                        {
                            "id": "序号, 为数字, 如: 1",
                            "step": "在这里填写查找不到则默认步骤是什么."
                        }
                    ]
                },
                "response": None
            },
            {
                "call": "critic",
                "execute": "AI",
                "description": "判断当前任务是否完成",
                "input": {
                    "task_id": "任务id",
                    "running": [
                        {
                            "call": "运行记录中按时间顺序排序的任务",
                            "return": "运行记录中对应的返回值"
                        }
                    ]
                },
                "response": {
                    "reasoning": "在这里显示分析过程",
                    "success": "标记任务是否完成, 如: True/False",
                    "critique": "如果success为false,请在这里说明应该如何完成任务"
                }
            },
            {
                "call": "set_task_info",
                "execute": "system",
                "description": "设定当前任务目标, Master允许时才能调用这个",
                "input": {
                    "task_id": "任务id",
                    "task_info": "",
                    "task_step": [
                        {
                            "id": "1",
                            "step": "执行设定的任务目标需要进行的操作"
                        }
                    ]
                },
                "response": None
            }
        ]
        self.tasks = {}
        self.now_task_id = "1"
        running: List[TaskRunningItem] = [
            TaskRunningItem(
                call='chat',
                execute='system',
                input={
                    "role": "Master",
                    "content": "你能帮我捶背吗?"
                }
            )
        ]
        task_step: List[TaskStepItem] = [
            TaskStepItem(
                id="1", 
                step="在这里为Master准备按摩板和油."
            )
        ]
        task = TaskItem(
            task_id=self.now_task_id,
            task_info="给Master按摩",
            task_step=task_step,
            sync_tool=self.sync_tool,
            running=running
        )
        self.tasks[self.now_task_id] = task

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return
            
        limit: int = 512
        for run in reversed(self.tasks[self.now_task_id].running):
            if len(str(running)) > limit:
                break
            running.insert(0, run)
        self.tasks[self.now_task_id].running = running

    def ask(
        self,
        aimi_name: str,
        preset: str,
        question: str
    ) -> Generator[dict, None, None]:
        answer = {
            "code": 1,
            "message": ""
        }
        task = self.make_task(aimi_name, preset, question)
        context_messages = make_context_messages(task, "你只能按照我规定的json格式回复.", [])

        for res in openai_api.ask(question, '', context_messages):
            if res['code'] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                continue

            for talk in self.task_response(res['message']):
                log_dbg(f"talk: {str(talk)}")
                answer['message'] += talk
                yield answer
        
        answer['code'] = 0
        yield answer

    def make_task(
        self, 
        aimi_name: str, 
        preset: str,
        question: str,
    ):
        if not (self.now_task_id in self.tasks):
            log_err(f"no task {str(self.now_task_id)}.")
            return
        chat = self.make_chat(question)
        self.__append_running([chat])
        return f"""```json
{str(self.tasks[self.now_task_id])}
```

你必须严格遵守以下条件:
1. 你需要生成 {aimi_name} 的响应.
2. 行动指南:{aimi_name}只能调用 sync_tool 中列出的方法.  running 中保存了时间顺序的运行记录. {aimi_name} 通过 task_step 完成 task_info. 如果 task_step 为空, 则要先查询是否存在task_step, 同时并附上如何完成 task_info 的默认步骤. 如果行动调用了 sync_tool 中 execute 字段是 system 的方法, 则马上终止生成{aimi_name}的行动,立刻把结构发给我执行.需要和我交互时,如果我已经同意,请尽快推进进度,我的话优先于当前计划.
3. {aimi_name}的预设： {{
{preset}
}}
4. 响应要求: 响应可以被Python的`json.loads`解析。 你的回复必须没有逗号结尾，没有单反引号 ` 等。你的回复要尽量精简,限制在 4000 内越短越好. 以JSON格式响应生成{aimi_name}行动, {aimi_name}行动定义如下所示:
[
    {{
        "call": "要调用的方法",
        "execute": "system 或 AI",
        "input": {{}},
        "response": "sync_tool->execute 字段是 AI 是才能填这个字段",
        "reasoning": "在这里显示分析过程"
    }},
    {{
    }},
    ...
]"""

    def set_running(self, api_response):
        self.running = json.loads(api_response)

task = Task()