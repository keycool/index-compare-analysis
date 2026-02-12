#!/usr/bin/env python3
"""
将Jupyter Notebook中的PDF保存改为PNG格式，避免使用os模块
"""

import json

def convert_pdf_to_png(notebook_path):
    """将Notebook中的PDF保存代码改为PNG格式"""
    
    # 读取Notebook文件
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook_data = json.load(f)
    
    # 查找第12个单元格（第三部分）
    cells = notebook_data.get('cells', [])
    
    for i, cell in enumerate(cells):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            
            # 查找包含"第三部分：完整历史比价图表"的单元格
            if source and "第三部分：完整历史比价图表" in source[0]:
                print(f"找到第{i+1}个单元格（第三部分）")
                
                # 修改代码：将PDF保存改为PNG，移除os模块依赖
                new_source = []
                
                for line in source:
                    # 移除import os语句
                    if "import os" in line:
                        continue
                    
                    # 修改PDF保存为PNG保存
                    elif "output_pdf = os.path.join(source_dir, '行业ETF_Report.pdf')" in line:
                        new_source.append("# 直接保存为PNG格式，避免使用os模块\n")
                        new_source.append("output_png = '行业ETF_Report.png'\n")
                    
                    # 修改plt.savefig调用
                    elif "plt.savefig(output_pdf, bbox_inches='tight')" in line:
                        new_source.append("plt.savefig(output_png, dpi=300, bbox_inches='tight')\n")
                    
                    # 修改打印语句
                    elif "print(f'图表已保存为PDF: {output_pdf}')" in line:
                        new_source.append("print(f'图表已保存为PNG: {output_png}')\n")
                    
                    else:
                        new_source.append(line)
                
                cell['source'] = new_source
                print("已成功将PDF保存改为PNG格式")
                break
    
    # 查找第13个单元格（第四部分）
    for i, cell in enumerate(cells):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            
            # 查找包含"第四部分：最近250个交易日比价图表"的单元格
            if source and "第四部分：最近250个交易日比价图表" in source[0]:
                print(f"找到第{i+1}个单元格（第四部分）")
                
                # 修改代码：将PDF保存改为PNG，移除os模块依赖
                new_source = []
                
                for line in source:
                    # 移除import os语句
                    if "import os" in line:
                        continue
                    
                    # 修改PDF保存为PNG保存
                    elif "output_pdf = os.path.join(source_dir, '行业ETF_250Days_Report.pdf')" in line:
                        new_source.append("# 直接保存为PNG格式，避免使用os模块\n")
                        new_source.append("output_png = '行业ETF_250Days_Report.png'\n")
                    
                    # 修改plt.savefig调用
                    elif "plt.savefig(output_pdf, bbox_inches='tight')" in line:
                        new_source.append("plt.savefig(output_png, dpi=300, bbox_inches='tight')\n")
                    
                    # 修改打印语句
                    elif "print(f'图表已保存为PDF: {output_pdf}')" in line:
                        new_source.append("print(f'图表已保存为PNG: {output_png}')\n")
                    
                    else:
                        new_source.append(line)
                
                cell['source'] = new_source
                print("已成功将PDF保存改为PNG格式")
                break
    
    # 保存修改后的Notebook
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(notebook_data, f, indent=2, ensure_ascii=False)
    
    print(f"Notebook文件已修改: {notebook_path}")

def create_png_test_script():
    """创建测试PNG保存功能的脚本"""
    
    test_script = """#!/usr/bin/env python3
# 测试PNG图片保存功能

import matplotlib.pyplot as plt
import numpy as np

# 创建测试图表
fig, ax = plt.subplots(figsize=(8, 6))
x = np.linspace(0, 10, 100)
y = np.sin(x)

ax.plot(x, y, label='正弦曲线')
ax.set_title('PNG保存功能测试')
ax.legend()
ax.grid(True)

# 保存为PNG格式（不使用os模块）
output_file = 'test_png_save.png'
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f'测试图表已保存为: {output_file}')

plt.show()
print("PNG保存功能测试完成！")
"""
    
    with open('test_png_save.py', 'w', encoding='utf-8') as f:
        f.write(test_script)
    
    print("测试脚本已创建: test_png_save.py")

if __name__ == "__main__":
    notebook_file = "指数比价关系.ipynb"
    
    print("开始将Notebook中的PDF保存改为PNG格式...")
    convert_pdf_to_png(notebook_file)
    create_png_test_script()
    
    print("\n修改完成！")
    print("现在Notebook将直接保存PNG图片，不再依赖os模块")
    print("\n可以运行以下命令测试PNG保存功能：")
    print("python test_png_save.py")
    print("\n然后重新运行Jupyter Notebook，第12个单元格应该可以正常工作了！")