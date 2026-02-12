#!/usr/bin/env python3
"""
修复Jupyter Notebook中os模块未定义问题的脚本
"""

import json
import os

def fix_notebook_os_issue(notebook_path):
    """修复Notebook中的os模块导入问题"""
    
    # 读取Notebook文件
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook_data = json.load(f)
    
    # 查找第12个单元格（索引为11）
    cells = notebook_data.get('cells', [])
    
    if len(cells) > 11:
        cell_12 = cells[11]
        
        # 检查单元格类型和内容
        if cell_12.get('cell_type') == 'code':
            source = cell_12.get('source', [])
            
            # 检查是否已经包含import os
            has_import_os = any('import os' in line for line in source)
            
            if has_import_os:
                print("第12个单元格已包含import os语句")
                
                # 在import os语句后添加importlib.reload(os)
                new_source = []
                importlib_added = False
                
                for line in source:
                    new_source.append(line)
                    if 'import os' in line and not importlib_added:
                        # 在import os后添加importlib相关代码
                        new_source.append('import importlib\n')
                        new_source.append('importlib.reload(os)\n')
                        importlib_added = True
                
                if importlib_added:
                    cell_12['source'] = new_source
                    print("已添加importlib.reload(os)语句")
                else:
                    print("未找到合适的位置添加importlib语句")
            else:
                # 如果没有import os，在开头添加
                new_source = [
                    'import importlib\n',
                    'import os\n',
                    'import matplotlib.pyplot as plt\n',
                    'importlib.reload(os)\n',
                    '\n'
                ]
                new_source.extend(source)
                cell_12['source'] = new_source
                print("已添加完整的导入语句")
    
    # 保存修复后的Notebook
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(notebook_data, f, indent=2, ensure_ascii=False)
    
    print(f"Notebook文件已修复: {notebook_path}")

def create_test_script():
    """创建测试脚本验证os模块功能"""
    
    test_script = """#!/usr/bin/env python3
# 测试os模块功能的脚本

import os
import sys

print("=== os模块功能测试 ===")
print(f"当前工作目录: {os.getcwd()}")
print(f"Python版本: {sys.version}")

# 测试文件路径操作
current_dir = os.path.dirname(os.path.abspath(__file__))
print(f"脚本所在目录: {current_dir}")

# 测试路径拼接
test_file = os.path.join(current_dir, 'test_output.txt')
print(f"测试文件路径: {test_file}")

print("os模块功能正常！")
"""
    
    with open('test_os_module.py', 'w', encoding='utf-8') as f:
        f.write(test_script)
    
    print("测试脚本已创建: test_os_module.py")

if __name__ == "__main__":
    notebook_file = "指数比价关系.ipynb"
    
    if os.path.exists(notebook_file):
        print(f"找到Notebook文件: {notebook_file}")
        fix_notebook_os_issue(notebook_file)
        create_test_script()
        
        print("\n修复完成！请运行以下命令测试：")
        print("python test_os_module.py")
        print("\n然后可以尝试重新启动Jupyter Notebook")
    else:
        print(f"未找到Notebook文件: {notebook_file}")
        print("请确保脚本在与Notebook相同的目录下运行")