from tools.base import Tool

class ToolRegistry:
    def __init__(self):
        self.tools={}
    def register(self,tool:Tool):
        if tool.name in self.tools:
            raise ValueError(
                f"tool already register:{tool.name}"
            )
        self.tools[tool.name]=tool
    def get(self,name):
        if name not in self.tools:
            raise ValueError(
                f"tool not found:{name}"
            )
        return self.tools[name]
    def all(self):
        return list(self.tools.values())
    def schemas(self,tools=None):
        if tools is None:
            tools=self.all()
        return[
            tool.schema()
            for tool in tools
        ]
    def execute(self,name,arguments):
        tool=self.get(name)
        return tool.run(arguments)
    def search(self,query):
        query=query.lower()
        words=query.split()
        results=[]
        for tool in self.tools.values():
            text=(
                tool.name+
                " "
                +tool.description
            ).lower()

            score=sum(
                word in text
                for word in words
            )
            if score>0:
                results.append((score,tool))
        results.sort(
            key=lambda item:item[0],
            reverse=True,
        )
        return [
            tool
            for _,tool in results
        ]