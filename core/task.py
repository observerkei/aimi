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
    reasoning: Optional[Union[str, None]] = None
    call: str
    input: Any
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
    max_running_size: int = 8 * 1000
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
                        log_err(f"{str(task.call)}: AI try predict system set response: {str(task.response)}")

                    
                    if task.call == "chat":
                        name = task.input['name']
                        content = task.input['content']
                        response = self.chat(name, content)
                        if 'Master' == name:
                            log_err(f"{str(task.call)}: AI try predict Master res as: {str(content)}")
                            continue
                        yield response
                    elif task.call == 'set_task_step':
                        task_id: str = task.input['task_id']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        step = self.set_task_step(task_id, task_step)
                        log_dbg(f"{str(task.call)}: finded step: {str(step)}")
                    elif task.call == 'set_task_info':
                        task_id: str =  task.input['task_id']
                        task_info: str = task.input['task_info']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        self.set_task_info(task_id, task_info, task_step)
                        log_dbg(f"{str(task.call)}: set task: {str(task_info)} : {str(task_step)}")
                    elif task.call == 'critic':
                        self.critic(task.input)
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
        name: str, 
        content: str
    ) -> str:
        log_dbg(f"{name}: {content}")
        if name != self.aimi_name:
            return ''
        return content + '\n'
    
    def make_chat(
        self,
        name: str,
        question: str
    ) -> TaskRunningItem:
        chat: TaskRunningItem = TaskRunningItem(
            timestamp=str(self.timestamp),
            call='chat',
            input={
                'name': name,
                'content': question
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
            task.task_step = task_step
            log_dbg(f"set task[{str(task_id)}] step: {str(task_step)}")
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
                log_dbg(f"set task[{str(task_id)}] info: {str(task_info)} step: {str(task_step)}")
                log_dbg(f"set task id {str(self.now_task_id)} to {str(task_id)}")
                self.now_task_id = task_id
                return task
        task = TaskItem(
            timestamp=str(self.timestamp),
            task_id=task_id,
            task_info=task_info,
            task_step=task_step
        )
        self.timestamp += 1
        self.tasks[task_id] = task
        self.now_task_id = task_id

        log_dbg(f"set new task[{str(task_id)}] info: {str(task_info)} step: {str(task_step)}")
        log_dbg(f"set task id {str(self.now_task_id)} to {str(task_id)}")
        return task

    def critic(
        self,
        input
    ):
        try:
            if input['success'] == 'True' or input['success'] == True:
                task = self.tasks[self.now_task_id]
                task_info = task.task_info
                log_info(f"task complate: {str(task_info)}")
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
            log_err(f"fail to critic {str(input)} : {str(e)}")

    def __init__(self):
        try:
            self.__load_task()
        except Exception as e:
            log_err(f"fait to init: {str(e)}")
    
    def __load_task(self):
        self.action_tool: List[SyncToolItem] = [
            SyncToolItem(
                call="chat",
                description="给某对象发送消息, 发件人写在 name 你和Aimi都不准填 Master. 内容写在 content 中.",
                input={
                    "name": "只能是 Aimi",
                    "content": "传达的内容, 可以很丰富"
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
                description="判断当前任务是否完成, 需要输入 task_id 和调用的对象的 timestamp , 如果数量太多, 只填写关健几个, 可以查找所有运行记录.",
                input={
                    "task_id": "被检查的task对应的id",
                    "task_info": "被检查的任务目标",
                    "running": [
                        "调用对象的 timestamp"
                    ],
                    "success": "标记任务是否完成, 如: True/False",
                    "critique": "如果success为 False, 请在这里说明应该如何完成任务"
                },
                execute="AI"
            ),
            SyncToolItem(
                call="set_task_info",
                description="设定当前任务目标, 设置目标的时候要同时给出实现步骤, Master允许时才能调用这个",
                input={
                    "task_id": "需要设置的task 对应的 id",
                    "task_info": "任务目标",
                    "task_step": [
                        {
                            "id": "步骤id, 如: 1",
                            "step": "执行设定的任务目标需要进行的操作"
                        }
                    ]
                },
                execute="AI"
            ),
            SyncToolItem(
                call="get_wolfram_response",
                description="通过wolfram进行计算, 所有计算都可以通过这个函数解决, 这个函数调用成功后是完全正确的.",
                input="在这里输入wolfram支持的内容, 只支持英文内容. 如: solve int x^2 dx ",
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
            self.make_chat('Master', '请保持设定'),
            self.make_chat('Aimi', '好')
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


        # 如果只是想让任务继续, 就回复全空格/\t/\n
        if (
            len(question)
            and not question.isspace()
        ):
            chat = self.make_chat('Master', question)
            self.__append_running([chat])

        # running_format = self.get_running()
        task_messages = self.make_task_messages(aimi_name, preset, task)

        context_messages = make_context_messages(task_messages, '', [])

        for res in openai_api.ask(question, 'gpt-3.5-turbo-16k', context_messages):
            if res['code'] != 0:
                log_dbg(f"skip len: {len(str(res['message']))}")
                if len(str(res['message'])) > 2000:
                    log_dbg(f"msg: {str(res['message'])}")
                continue

            for talk in self.task_response(res['message']):
                log_dbg(f"recv task chat: {str(talk)}")
                answer['message'] += talk
                yield answer
        
        answer['code'] = 0
        yield answer
    
    def make_task_messages(
        self,
        aimi_name: str,
        preset: str,
        task: Dict
    ) -> str:
        response_format = f"""```json
[
    {{
        "timestamp": "时间戳: 执行当前调用的时间, 每次递增, 从最大 timestamp 开始算.",
        "call": "调用方法: 需要使用哪个 action_tool.",
        "reasoning": "推理过程: 在这里显示分析过程和建议或运行记录.",
        "input": {{ "对应入参": "对应内容" }},
        "execute": "执行类型: 在 action_tool 中定义, 不能漏掉, 只能填写 system 或者 AI "
    }}
]
```"""
        action_tool = [item.dict() for item in self.action_tool]
        task = self.make_task()
        settings: Dict = {
            "settings": [
                f"action_tool 里面定义了所有你能调用的 方法(action).",
                f"你每次生成追加内容时, 可以同时生成多个方法(action), 但最多只能生成一次 action->execute 为 system 的方法.",
                f"可以生成不限次 action->execute 为 AI 的方法, 但是要控制频率, 尽量减少重复消息.",
                f"当你在调用 action_tool 中 execute 是 system 的 action 时不要填写 response, 也不要说明任何和 response 有关内容, 除非调用成功.",
                f"task 中定义了 {aimi_name} 你当前任务, 其中 task_info 是任务目标, task_step 是完成 task_info 需要进行的步骤.",
                f"如果 task_step 为空, 或不符合 或没有进展, 请重新设置步骤, 尽量推进任务进度.",
                f"你将扮演 {aimi_name}. 你会遵守 settings, 你通过 action_tool 行动. 你叫我 Master.",
                f"preset 是 {aimi_name} 的预设, preset 只能对 action_tool 中定义的方法的输入生效.",
                f"{aimi_name} 的权限不会超过action_tool中定义的范围.",
                f"请你主要基于 settings 和 参考部分 action_running 分析, 不显示分析过程, 然后你只以 {aimi_name} 的身份只生成 action_running 的追加内容",
                f"只给我发送追加内容即可, 如果 action_running 太长, 请只重点关注最后几条和我的话, 忽略重复消息.",
                f"大多数情况下 Master 不会回 {aimi_name} 消息, 你也不需要找Master. 你生成追加内容的时候要考虑这一点.",
                f"你的回复是 [{{action}}] 的 JSON 数组结构, action 在 action_tool 中定义.",
                f"不要漏了填充 action->execute.",
                f"请保持你的回复可以被 Python 的 `json.loads` 解析, 请严格按照以下JSON数组格式回复我: {response_format}"
            ],
            "task": task,
            "action_tool": action_tool,
            "preset": preset,
            "action_running": [item.dict() for item in self.running]
        }
        setting_format = json.dumps(settings, ensure_ascii=False)

        log_dbg(f"now setting: {json.dumps(settings, indent=4, ensure_ascii=False)}")

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
