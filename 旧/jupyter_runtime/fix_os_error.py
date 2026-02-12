#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复Jupyter Notebook中os模块导入错误的脚本
"""

import json

def fix_os_import_error():
    """修复第12个单元格的os模块导入错误"""
    
    notebook_file = "指数比价关系.ipynb"
    
    try:
        # 读取Notebook文件
        with open(notebook_file, 'r', encoding='utf-8') as f:
            notebook_data = json.load(f)
        
        # 查找第12个单元格（索引从0开始）
        cells = notebook_data['cells']
        
        for i, cell in enumerate(cells):
            if cell.get('cell_type') == 'code':
                # 查找包含"第三部分：完整历史比价图表"的单元格
                source = cell.get('source', [])
                if source and "第三部分：完整历史比价图表" in source[0]:
                    print(f"找到第{i+1}个单元格（第12个单元格）")
                    
                    # 检查是否已导入os
                    has_os_import = any("import os" in line for line in source)
                    
                    if has_os_import:
                        print("单元格已包含import os语句")
                        print("问题可能是内核状态问题，建议重启内核")
                    else:
                        print("单元格缺少import os语句，正在修复...")
                        # 在import matplotlib.pyplot as plt后添加import os
                        new_source = []
                        for line in source:
                            new_source.append(line)
                            if "import matplotlib.pyplot as plt" in line:
                                new_source.append("import os\n")
                        
                        cell['source'] = new_source
                        
                        # 保存修改后的文件
                        with open(notebook_file, 'w', encoding='utf-8') as f:
                            json.dump(notebook_data, f, indent=2, ensure_ascii=False)
                        
                        print("修复完成！")
                    
                    break
        else:
            print("未找到第12个单元格")
            
    except FileNotFoundError:
        print(f"文件 {notebook_file} 不存在")
    except Exception as e:
        print(f"处理文件时出错: {e}")

def main():
    """主函数"""
    print("开始修复Jupyter Notebook中的os模块导入错误...")
    fix_os_import_error()
    
    print("\n建议的解决方案：")
    print("1. 重启Jupyter Notebook内核")
    print("2. 在第12个单元格开头添加以下代码：")
    print("""
# 强制重新导入必要的模块
import importlib
import matplotlib.pyplot as plt
import os
importlib.reload(os)
""")

if __name__ == "__main__":
    main()