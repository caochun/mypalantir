# 高速公路收费路段地图可视化

## 功能说明

这是一个基于高德地图 JS API 2.0 的高速公路收费路段可视化页面，展示从 `TBL_GBSECTIONDIC` 表中提取的所有路段数据。

## 使用方法

### 方式一：直接打开HTML文件

1. 在浏览器中打开 `toll-sections-map.html`
2. 确保 `sections-data.js` 文件在同一目录下
3. 页面会自动加载并显示所有路段

### 方式二：通过Web服务器访问

如果通过Web服务器访问（推荐），可以：

```bash
# 如果使用Python
cd web/public
python3 -m http.server 8000

# 然后访问
http://localhost:8000/toll-sections-map.html
```

## 功能特性

1. **地图展示**
   - 使用高德地图展示所有收费路段
   - 路段用不同颜色的折线表示（类型1为蓝色，类型2为橙色）
   - 起点和终点用标记点标识

2. **搜索功能**
   - 在搜索框中输入路段名称进行实时搜索
   - 支持中文搜索

3. **筛选功能**
   - 按路段类型筛选（类型1/类型2）
   - 按状态筛选（有效/无效）

4. **交互功能**
   - 点击路段折线查看详细信息
   - 鼠标悬停时路段高亮显示
   - 信息窗体显示路段的完整信息

5. **统计信息**
   - 显示总路段数
   - 显示当前筛选后的路段数

## 数据说明

- 数据来源：`scripts/TBL_GBSECTIONDIC.sql`
- 数据文件：`sections-data.js`（自动生成）
- 数据条数：145条路段记录

## 配置信息

- **API Key**: 2a4bc1182904741a0b47e7c308143cde
- **安全密钥**: 03b411983871fcf6d0f4fb7e5e8e857b

## 更新数据

如果需要更新数据，可以运行以下命令重新生成数据文件：

```bash
cd /Users/chun/Develop/mypalantir
node -e "
const fs = require('fs');
const sqlContent = fs.readFileSync('scripts/TBL_GBSECTIONDIC.sql', 'utf-8');
const regex = /VALUES\s+\('([^']+)','([^']+)','([^']+)','([^']+)',(\d+),(\d+),'([^']+)','([^']+)','([^']+)','([^']+)','([^']+)','([^']+)',(\d+),([\d.]+),(\d+),'([^']+)',TIMESTAMP'([^']+)',TIMESTAMP'([^']+)',TIMESTAMP'([^']+)',(\d+),TIMESTAMP'([^']+)','([^']+)','([^']+)',(\d+),'([^']+)',TIMESTAMP'([^']+)',TIMESTAMP'([^']+)',([^,]+),([^,]+),(\d+),(\d+)\)/g;
const sections = [];
let match;
while ((match = regex.exec(sqlContent)) !== null) {
    sections.push({
        ID: match[1], ROADID: match[2], NAME: match[3], SECTIONOWNERID: match[4],
        TYPE: parseInt(match[5]), LENGTH: parseInt(match[6]), STARTSTAKENUM: match[7],
        STARTLAT: parseFloat(match[8]), STARTLNG: parseFloat(match[9]), ENDSTAKENUM: match[10],
        ENDLAT: parseFloat(match[11]), ENDLNG: parseFloat(match[12]), TAX: parseInt(match[13]),
        TAXRATE: parseFloat(match[14]), CHARGETYPE: parseInt(match[15]), TOLLROADS: match[16],
        BUILTTIME: match[17], STARTTIME: match[18], ENDTIME: match[19], STATUS: match[22]
    });
}
fs.writeFileSync('web/public/sections-data.js', 'window.sectionsData = ' + JSON.stringify(sections, null, 2) + ';', 'utf-8');
console.log('数据已更新');
"
```

## 注意事项

1. 确保网络连接正常，以便加载高德地图API
2. 如果地图无法显示，请检查API Key是否有效
3. 数据文件较大（145条记录），首次加载可能需要几秒钟
4. 建议使用现代浏览器（Chrome、Firefox、Edge等）
