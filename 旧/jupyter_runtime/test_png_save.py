#!/usr/bin/env python3
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
