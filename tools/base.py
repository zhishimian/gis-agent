from dataclasses import dataclass
from typing import Any,Callable
@dataclass
class Tool:
    name:str
    description:str
    parameters:dict
    function:Callable[...,Any]

    def schema(self):
        return {
            "type":"function",
            "function":{
                "name":self.name,
                "description":self.description,
                "parameters":self.parameters,
            },
        }
    def run(self,arguments):
        return self.function(**arguments)