import json5
import json
from typing import Dict, Any, List, Generator, Optional, Union
from pydantic import BaseModel, constr

from tool.openai_api import openai_api
from tool.wolfram_api import wolfram_api
from tool.bard_api import bard_api
from tool.util import log_dbg, log_err, log_info, make_context_messages

class TaskStepItem(BaseModel):
    id: str
    step: str

class SyncToolItem(BaseModel):
    call: str
    description: str
    input: Any
    response: Any
    execute: constr(regex='system|AI')

class TaskRunningItem(BaseModel):
    timestamp: str = ''
    call: str
    input: Any
    reasoning: Optional[Union[str, None]] = None
    response: Any = None
    execute: constr(regex='system|AI')

class TaskItem(BaseModel):
    timestamp: str
    task_id: str
    task_info: str
    task_step: List[TaskStepItem] = []


class Task():
    type: str = 'task'
    tasks: Dict[str, TaskItem]
    action_tool: List[SyncToolItem]
    now_task_id: str
    aimi_name: str = 'Aimi'
    running: List[TaskRunningItem] = []
    max_running_size: int = 3500
    timestamp: int = 1

    def task_response(
        self, 
        res: str
    ) -> Generator[dict, None, None]:
        log_dbg(f"now task: {str(self.tasks[self.now_task_id].task_info)}")

        response = ''
        try:
            answer = res
            start_index = answer.find("```json\n[")
            if start_index == -1:
                start_index = answer.find("[")
            else:
                start_index += 8
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

            # 忽略错误.
            # decoder = json.JSONDecoder(strict=False)
            # data = decoder.decode(answer)
            data = json5.loads(answer)

            tasks = []
            try:
                tasks = [TaskRunningItem(**item) for item in data]
            except Exception as e:
                log_err(f"res not arr...: {e}\n{str(res)}")
                if data[0] == '{':
                    log_dbg(f"try load one obj")
                    task = TaskItem.parse_obj(data)
                    tasks = [task]
            
            running: List[TaskRunningItem] = []
            for task in tasks:
                try:
                    log_dbg(f"get task: {str(task)}")
                    if task.reasoning:
                        log_dbg(f"reasoning: {str(task.reasoning)}")
                    if (
                        task.execute == "system"
                        and task.response
                    ):
                        log_err(f"AI try predict system call {str(task.call)} response: {str(task.response)}")

                    
                    if task.call == "chat":
                        source = task.input['source']
                        content = task.input['content']
                        response = self.chat(source, content)
                        if 'Master' == source:
                            log_err(f"AI try predict Master res as: {str(content)}")
                            continue
                        yield response
                    elif task.call == 'set_task_step':
                        task_id: str = task.input['task_id']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        step = self.set_task_step(task_id, task_step)
                        log_dbg(f"finded step: {str(step)}")
                    elif task.call == 'set_task_info':
                        task_id: str =  task.input['task_id']
                        task_info: str = task.input['task_info']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        self.set_task_info(task_id, task_info, task_step)
                        log_dbg(f"set task: {str(task_info)} : {str(task_step)}")
                    elif task.call == 'critic':
                        self.critic(task.response)
                    elif task.call == 'get_wolfram_response':
                        response = self.get_wolfram_response(task.input)
                        task.response = response
                    elif task.call == 'get_bard_response':
                        response = self.get_bard_response(task.input)
                        task.response = response
                    else:
                        log_err(f'no suuport call: {str(self.call)}')
                        continue
                    if (len(str(running)) + len(str(task))) < self.max_running_size:
                        running.append(task)
                except Exception as e:
                    log_err(f"fail to load task: {str(e)}: {str(task)}")
            self.__append_running(running)
            log_dbg(f"update running success: {len(running)} : {json.dumps(str(running), indent=2, ensure_ascii=False)}")
        except Exception as e:
            log_err(f"fail to load task res: {str(e)} : \n{str(res)}")
        
        yield ''


    def get_bard_response(
        self,
        input: str
    ) -> str:
        if not input or not len(input):
            return 'input error'

        answer = ''
        for res in bard_api.ask(input):
            if res['code'] != 0:
                continue
            answer = res['message']

        return answer
    
    def get_wolfram_response(
        self,
        input: str
    ) -> str:
        if not input or not len(input):
            return 'input error'
        answer = ''
        for res in wolfram_api.ask(input):
            if res['code'] != 0:
                continue
            answer = res['message']
        
        return answer


    def chat(
        self,
        source: str, 
        content: str
    ) -> str:
        log_dbg(f"{source}: {content}")
        if source != self.aimi_name:
            return ''
        return content + '\n'
    
    def make_chat(
        self,
        question: str
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            call='chat',
            input={
                'content': question,
                'source': 'Master'
            },
            execute='system'
        )
        self.timestamp += 1
        return chat

    def set_task_step(
        self,
        task_id: str, 
        task_step: List[TaskStepItem]
    ):
        for _, task in self.tasks.items():
            if task_id != task.task_id:
                continue
            if task.task_step:
                return task.task_step
            task.task_step = task_step
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
            timestamp=str(self.timestamp),
            task_id=task_id,
            task_info=task_info,
            task_step=task_step
        )
        self.timestamp += 1
        self.tasks[task_id] = task
        return task

    def critic(
        self,
        response
    ):
        try:
            if response['success']:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                if len(self.tasks) > 1:
                    del self.tasks[self.now_task_id]
                    log_info(f'task_info: {task_info}, delete.')
                
                    for _, task in self.tasks.items():
                        self.now_task_id = task.task_id
                        return
                else:
                    # 一个任务也没有了
                    new_task = self.tasks[self.now_task_id]
                    new_task.task_info = '当前没有事情可以做, 找Master聊天吧...'
                    new_task.task_step = [] # 清空原有步骤 ...

                    self.now_task_id = str(int(self.now_task_id) + 1)
                    self.tasks[self.now_task_id] = new_task
                    log_dbg(f"set task to {str(self.now_task_id)} : {str(self.tasks[self.now_task_id].task_info)}")
            else:
                log_dbg(f"task no complate, continue...")
                
        except Exception as e:
            log_err(f"fail to critic {str(response)} : {str(e)}")

    def __init__(self):
        try:
            self.__load_task()
        except Exception as e:
            log_err(f"fait to init: {str(e)}")
    
    def __load_task(self):
        self.action_tool: List[SyncToolItem] = [
            SyncToolItem(
                call="chat",
                description="给某对象发送消息, 发件人写 source, 内容写 content",
                input={
                    "content": "传达的内容, 可以很丰富",
                    "source": "Aimi|Master, 表示是谁填写的消息. 你只能生成 Aimi 的内容"
                },
                execute="system"
            ),
            SyncToolItem(
                call="set_task_step",
                description="如果 task_step 和目标(task_info)不符合或为空,则需要设置一下",
                input={
                    "task_id": "需要设置的task 对应的 id",
                    "task_step": [
                        {
                            "id": "序号, 为数字, 如: 1",
                            "step": "在这里填写能够完成计划的步骤"
                        }
                    ]
                },
                execute="AI"
            ),
            SyncToolItem(
                call="critic",
                description="判断当前任务是否完成, 只需要输入 task_id 和调用的对象的 timestamp 即可,如果数量太多,只填写关健几个,可以查找所有运行记录",
                input={
                    "task_id": "任务id",
                    "task_info": "被检查的任务目标",
                    "running": [
                        "调用对象的 timestamp"
                    ]
                },
                response={
                    "analysis": "在这里显示分析过程",
                    "success": "标记任务是否完成, 如: True/False",
                    "critique": "如果success为false,请在这里说明应该如何完成任务"
                },
                execute="AI"
            ),
            SyncToolItem(
                call="set_task_info",
                description="设定当前任务目标, 设置目标的时候要同时给出实现步骤, Master允许时才能调用这个",
                input={
                    "task_id": "任务id",
                    "task_info": "",
                    "task_step": [
                        {
                            "id": "1",
                            "step": "执行设定的任务目标需要进行的操作"
                        }
                    ]
                },
                execute="AI"
            ),
            SyncToolItem(
                call="get_wolfram_response",
                description="通过wolfram进行计算, 所有计算都可以通过这个函数解决, 这个函数调用成功后是完全正确的.",
                input="在这里输入wolfram支持的内容. 如: solve int x^2 dx ",
                execute="system"
            ),
            SyncToolItem(
                call="get_bard_response",
                description="通过互联网进行搜索, 需要了解任何有时效性的内容都可以调用, 只能搜索最新有时效性的信息, 比如时间/日期或者某个网址的内容等.",
                input="在这里输入要bard进行检索的内容, 输入必须为英文. 如: What time is it now?",
                execute="system"
            )
        ]
        self.tasks = {}
        self.now_task_id = "1"
        running: List[TaskRunningItem] = [
            TaskRunningItem(
                timestamp=str(self.timestamp),
                call='chat',
                execute='system',
                input={
                    "source": "Master",
                    "content": "请保持设定(不要回复这一句)."
                }
            )
        ]
        task_step: List[TaskStepItem] = [
            TaskStepItem(
                id="1", 
                step="偷偷接近Master."
            )
        ]
        task = TaskItem(
            timestamp=str(self.timestamp),
            task_id=self.now_task_id,
            task_info="想和Master亲密接触",
            task_step=task_step
        )
        self.timestamp += 1
        self.tasks[self.now_task_id] = task
        self.running = running

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return
        
        for run in reversed(self.running):
            if (len(str(running)) + len(str(run))) > self.max_running_size:
                break
            running.insert(0, run)
        self.running = running
        for run in self.running:
            run.timestamp = str(self.timestamp)
            self.timestamp += 1
    
    def get_running(self) -> str:
        run_dict = [item.dict() for item in self.running]
        js = json.dumps(run_dict, ensure_ascii=False)
        log_dbg(f"running: {json.dumps(run_dict, indent=4, ensure_ascii=False)}")
        return str(js)
    
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

        setting = self.make_setting(aimi_name, preset, task)

        # 如果只是想让任务继续, 就回复全空格/\t/\n
        if (
            len(question)
            and not question.isspace()
        ):
            chat = self.make_chat(question)
            self.__append_running([chat])

        running_format = self.get_running()

        context_messages = make_context_messages(running_format, setting, [])

        for res in openai_api.ask(question, '', context_messages):
            if res['code'] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                if len(str(res['message'])) > 2000:
                    log_dbg(f"msg: {str(res['message'])}")
                continue

            for talk in self.task_response(res['message']):
                answer['message'] += talk
                yield answer
        
        answer['code'] = 0
        yield answer
    
    def make_setting(
        self,
        aimi_name: str,
        preset: str,
        task: Dict
    ) -> str:
        response_format = f"""```json
[
    {{
        "timestamp": "执行当前调用的时间, 每次递增, 从我发送的最后一项 timestamp 开始算.",
        "call": "要调用的方法如果是多个, 也是放在这个数组里面.",
        "reasoning": "在这里显示分析过程和建议.",
        "input": {{ "对应入参": "对应内容" }},
        "execute": "system 或 AI"
    }}
]
```"""
        action_tool = [item.dict() for item in self.action_tool]
        task = self.make_task()
        setting: Dict = {
            "action_tool": action_tool,
            "task": task,
            "preset": preset,
            "setting": [
                f"你需要根据 setting 生成 {aimi_name} 的动作. {aimi_name} 基于 setting 运行",
                f"preset 是 {aimi_name} 的预设, 只能对 action_tool 中定义的方法的输入生效.",
                f"system 的动作是系统执行, 无论怎样你生成的内容中这个类型的动作只能出现一次.",
                f"system 的动作的 response 是 None 时, 不要说明任何和返回值有关的内容.",
                f"task->task_info 是目标, task->task_step 是完成 task->task_info 需要进行的步骤. 如果 task->task_step 为空, 或不符合, 请重新设置步骤.",
                f"你需要用 setting 条件回复我, 只回复新生成的内容.",
                f"如果你不能回答, 请给出能够回答的示例.",
                f"你的回复是从 action_tool 里面挑选的动作.",
                f"任何时候请不要生成任何和 Master 相关的内容.",
                f"请保持你的回复可以被 Python 的 `json.loads` 解析, json 外部不需要反引号包裹. json 的参数内部如果有双引号 \" 则进行转义.",
                f"请严格按照以下格式回复我(请用 [{{action}}, {{action}}] 类似方式回复我): {response_format}",
            ]
        }
        setting_format = json.dumps(setting, ensure_ascii=False)

        log_dbg(f"now setting: {json.dumps(setting, indent=4, ensure_ascii=False)}")

        return setting_format

    def make_task(
        self
    ) -> Dict:
        if not (self.now_task_id in self.tasks):
            log_err(f"no task {str(self.now_task_id)}.")
            return
        
        # log_dbg(f"make task: {self.tasks[self.now_task_id].json(indent=2,ensure_ascii=False)}")
        
        return self.tasks[self.now_task_id].dict()

    def set_running(self, api_response):
        self.running = json.loads(api_response)

task = Task()
