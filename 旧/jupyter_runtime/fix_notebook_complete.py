#!/usr/bin/env python3
"""
完全修复Notebook中的os模块问题
"""

import json

def fix_notebook_completely(notebook_path):
    """完全修复Notebook中的os模块问题"""
    
    # 读取Notebook文件
    with open(notebook_path, 'r', encoding='utf-8') as f:
        notebook_data = json.load(f)
    
    cells = notebook_data.get('cells', [])
    
    # 修复第14个单元格（第三部分）
    for i, cell in enumerate(cells):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            
            # 查找包含"第三部分：完整历史比价图表"的单元格
            if source and "第三部分：完整历史比价图表" in source[0]:
                print(f"修复第{i+1}个单元格（第三部分）")
                
                # 创建新的源代码
                new_source = []
                
                for line in source:
                    # 移除import os语句
                    if "import os" in line:
                        continue
                    
                    # 移除os.path相关代码
                    elif "source_dir = os.path.dirname(os.path.abspath('your_source_data.csv'))" in line:
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
                print("第14个单元格修复完成")
                break
    
    # 修复第15个单元格（第四部分）
    for i, cell in enumerate(cells):
        if cell.get('cell_type') == 'code':
            source = cell.get('source', [])
            
            # 查找包含"第四部分：最近250个交易日比价图表"的单元格
            if source and "第四部分：最近250个交易日比价图表" in source[0]:
                print(f"修复第{i+1}个单元格（第四部分）")
                
                # 创建新的源代码
                new_source = []
                
                for line in source:
                    # 移除import os语句
                    if "import os" in line:
                        continue
                    
                    # 移除os.path相关代码
                    elif "source_dir = os.path.dirname(os.path.abspath('your_source_data.csv'))" in line:
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
                print("第15个单元格修复完成")
                break
    
    # 保存修改后的Notebook
    with open(notebook_path, 'w', encoding='utf-8') as f:
        json.dump(notebook_data, f, indent=2, ensure_ascii=False)
    
    print(f"Notebook文件已完全修复: {notebook_path}")

def verify_fix():
    """验证修复是否成功"""
    
    with open('指数比价关系.ipynb', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否还有os模块相关代码
    if "import os" in content:
        print("警告：Notebook中仍然存在import os语句")
    else:
        print("✓ import os语句已移除")
    
    if "os.path.dirname" in content:
        print("警告：Notebook中仍然存在os.path.dirname")
    else:
        print("✓ os.path.dirname已移除")
    
    if "os.path.join" in content:
        print("警告：Notebook中仍然存在os.path.join")
    else:
        print("✓ os.path.join已移除")
    
    if "output_png = '行业ETF_Report.png'" in content:
        print("✓ PNG输出配置已添加")
    else:
        print("警告：PNG输出配置未找到")

if __name__ == "__main__":
    notebook_file = "指数比价关系.ipynb"
    
    print("开始完全修复Notebook中的os模块问题...")
    fix_notebook_completely(notebook_file)
    
    print("\n验证修复结果...")
    verify_fix()
    
    print("\n=== 修复完成！ ===")
    print("现在Notebook已经完全移除了os模块依赖")
    print("第12个单元格（实际上是第14个单元格）应该可以正常工作了！")
    print("\n你可以重新启动Jupyter Notebook进行测试")