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
    uuid: str = ''
    call: str
    execute: str = ''
    input: Any
    reasoning: str = None
    response: Any = None

class TaskItem(BaseModel):
    task_id: str
    task_info: str
    task_step: List[TaskStepItem]
    sync_tool: List[SyncToolItem]
    preset: str = ""


class Task():
    type: str = 'task'
    tasks: Dict[str, TaskItem]
    sync_tool: List[SyncToolItem]
    now_task_id: str
    aimi_name: str = 'Aimi'
    running: List[TaskRunningItem] = []
    max_running_size: int = 2048

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
            decoder = json.JSONDecoder(strict=False)
            data = decoder.decode(answer)

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
            running_size: int = 0
            for task in tasks:
                try:
                    log_dbg(f"get task: {str(task)}")
                    if task.reasoning:
                        log_dbg(f"reasoning: {str(task.reasoning)}")
                    
                    if task.call == "chat":
                        source = task.input['source']
                        content = task.input['content']
                        response = self.chat(source, content)
                        if 'Master' == source:
                            log_err(f"AI try predict Master res as: {str(content)}")
                            continue
                        yield response
                    elif task.call == 'find_task_step':
                        task_id: str = task.input['task_id']
                        default: List[TaskStepItem] = task.input['default']
                        step = self.find_task_step(task_id, default)
                        log_dbg(f"finded step: {str(step)}")
                    elif task.call == 'set_task_info':
                        task_id: str =  task.input['task_id']
                        task_info: str = task.input['task_info']
                        task_step: List[TaskStepItem] = task.input['task_step']
                        self.set_task_info(task_id, task_info, task_step)
                        log_dbg(f"set task: {str(task_info)} : {str(task_step)}")
                    elif task.call == 'critic':
                        self.critic(task.response)
                    else:
                        log_err(f'no suuport call: {str(self.call)}')
                        continue
                    if running_size < self.max_running_size:
                        running.append(task)
                        running_size += len(str(task))
                except Exception as e:
                    log_err(f"fail to load task: {str(e)}")
            self.__append_running(running)
            log_dbg(f"update running success: {len(running)} : {json.dumps(str(running), indent=2, ensure_ascii=False)}")
        except Exception as e:
            log_err(f"fail to load task res: {str(e)} : \n{str(res)}")
        
        yield ''

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
        now_idx = f"{len(self.running) + 1}"
        try:
            last_uuid = self.running[-1].uuid
            now_idx = f"{int(last_uuid)+1}"
        except Exception as e:
            log_err(f"fail to get run idx: {str(e)}")
        chat = TaskRunningItem(
            uuid=now_idx,
            call='chat',
            execute='system',
            input={'source':'Master', 'content':question}
        )
        return chat

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
            task_step=task_step
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
                    log_dbg(f"set task to {str(self.tasks[self.now_task_id].task_info)}")
                
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
                "description": "给某对象发送消息,发件人写 source, 内容写 content, 请注意 你只能把 source 填写成为 Aimi .",
                "input": {
                    "source": "是谁填写的消息.",
                    "content": "传达的内容."
                }
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
                            "step": "在这里填写能够完成计划的步骤."
                        }
                    ]
                }
            },
            {
                "call": "critic",
                "execute": "AI",
                "description": "判断当前任务是否完成, 只需要输入任务id 和调用的uuid即可",
                "input": {
                    "task_id": "任务id",
                    "running": [
                        {
                            "uuid": "调用的UUID"
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
                }
            }
        ]
        self.tasks = {}
        self.now_task_id = "1"
        running: List[TaskRunningItem] = [
            TaskRunningItem(
                uuid='1',
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
            task_id=self.now_task_id,
            task_info="想和Master亲密接触",
            task_step=task_step,
            sync_tool=self.sync_tool
        )
        self.tasks[self.now_task_id] = task
        self.running = running

    def __get_now_task(self):
        return self.tasks[self.now_task_id]

    def __append_running(self, running: List[TaskRunningItem]):
        if not (self.now_task_id in self.tasks):
            log_dbg(f"no now_task ... {str(self.now_task_id)}")
            return
        
        for run in reversed(self.running):
            if len(str(running)) > self.max_running_size:
                break
            running.insert(0, run)
        self.running = running
        idx = 1
        for run in self.running:
            run.uuid = f"{idx}"
            idx += 1
    
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

        task = self.make_task(preset)
        setting = self.make_setting(aimi_name, task)
        
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
        task: str
    ) -> str:
        response_format = f"""
[
    {{
        "uuid": "执行当前调用的uuid, 填写唯一的递增调用序号就行",
        "call": "要调用的方法如果是多个,也是放在这个数组里面.",
        "execute": "system 或 AI, 响应中的system只能出现一次",
        "input": {{}},
        "response": "sync_tool->execute 字段是 AI 是才能填这个字段",
        "reasoning": "在这里显示分析过程"
    }}
]
"""
        setting = [
            f"{task}",
            f"你需要生成 {aimi_name} 的行为.",
            f"{aimi_name} 需要想办法完成 task_info 和 Master的要求. task_step 是完成步骤. 如果 task_step 为空, 或不符合,请重新设置步骤.",
            f"如果{aimi_name}在行为中调用了 execute 为 system 的方法, 则在保证json结构完整情况下马上终止生成 {aimi_name} 任何 system 的 sync_tool 方法,然后把内容发给我. 当你使用 chat 接口时, input 的 source 不能填写 Master. 因为你会胡说(这很重要).",
            f"preset 是 {aimi_name} 的行为定义,只能对sync_tool生效.",
            f"如果我说停止当前计划,你还是需要保持调用 sync_tool 方法, 但是需要把当前 task_info 清空.",
            f"响应要求:请控制你的回复长度在3500字内,请减少调用次数.请保持内容连续,你不需要复制我的回复,而是继续补充后续仅限{aimi_name}身份和动作的内容.",
            f"请保持你的回复可以被Python的`json.loads`解析,json外部不需要反引号包裹.json的参数内部不要有双引号,请严格按照以下格式回复我.(请用 [{{}},{{}}] 方式回复我):{response_format}"
        ]
        setting = '\n'.join(setting)

        log_dbg(f"now setting: {setting}")

        return setting

    def make_task(
        self,
        preset: str
    ):
        if not (self.now_task_id in self.tasks):
            log_err(f"no task {str(self.now_task_id)}.")
            return
        self.tasks[self.now_task_id].preset = preset
        
        log_dbg(f"make task: {self.tasks[self.now_task_id].json(indent=2,ensure_ascii=False)}")
        
        return self.tasks[self.now_task_id].json(ensure_ascii=False)

    def set_running(self, api_response):
        self.running = json.loads(api_response)

task = Task()
