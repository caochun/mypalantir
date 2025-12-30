#!/bin/bash

# 创建测试数据脚本
BASE_URL="http://localhost:8080/api/v1"

echo "=========================================="
echo "创建省中心联网收费业务测试数据"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 存储创建的ID
declare -A IDs

# 创建函数
create_instance() {
    local object_type=$1
    local data=$2
    local name_field=$3
    local key=$4  # 可选的key，用于没有唯一标识字段的对象
    
    echo -e "${YELLOW}创建 ${object_type}...${NC}" >&2
    response=$(curl -s -X POST "${BASE_URL}/instances/${object_type}" \
        -H "Content-Type: application/json" \
        -d "$data")
    
    id=$(echo "$response" | jq -r '.data.id // empty' 2>/dev/null)
    if [ -n "$id" ] && [ "$id" != "null" ]; then
        echo -e "${GREEN}✓ 创建成功: ${id}${NC}" >&2
        if [ -n "$key" ]; then
            # 使用提供的key
            IDs["$key"]=$id
        elif [ -n "$name_field" ]; then
            # 使用name_field自动生成key
            name=$(echo "$data" | jq -r ".${name_field}" 2>/dev/null)
            if [ -n "$name" ] && [ "$name" != "null" ]; then
            IDs["${object_type}_${name}"]=$id
            fi
        fi
        echo "$id"  # 只输出ID到stdout，用于赋值
    else
        echo "✗ 创建失败: $response" >&2
        echo "" >&2
        return 1
    fi
    echo "" >&2
}

# 创建关系函数
create_link() {
    local link_type=$1
    local source_key=$2
    local target_key=$3
    local properties=$4
    
    source_id=${IDs[$source_key]}
    target_id=${IDs[$target_key]}
    
    if [ -z "$source_id" ] || [ -z "$target_id" ]; then
        echo "✗ 关系创建失败: 缺少源或目标ID (${source_key} -> ${target_key})"
        return 1
    fi
    
    echo -e "${YELLOW}创建关系 ${link_type}: ${source_key} -> ${target_key}...${NC}" >&2
    
    link_data="{\"source_id\": \"${source_id}\", \"target_id\": \"${target_id}\""
    if [ -n "$properties" ]; then
        link_data="${link_data}, \"properties\": ${properties}"
    fi
    link_data="${link_data}}"
    
    response=$(curl -s -X POST "${BASE_URL}/links/${link_type}" \
        -H "Content-Type: application/json" \
        -d "$link_data")
    
    id=$(echo "$response" | jq -r '.data.id // empty' 2>/dev/null)
    if [ -n "$id" ] && [ "$id" != "null" ]; then
        echo -e "${GREEN}✓ 关系创建成功${NC}" >&2
        echo "" >&2
        return 0
    else
        echo "✗ 关系创建失败: $response" >&2
        echo "" >&2
        return 1
    fi
}

echo "步骤 1: 创建路段业主"
create_instance "路段业主" '{"业主名称": "江苏交通控股有限公司", "统一社会信用代码": "91320000123456789X"}' "业主名称"
create_instance "路段业主" '{"业主名称": "浙江交通投资集团", "统一社会信用代码": "91330000987654321Y"}' "业主名称"

echo "步骤 2: 创建收费公路"
create_instance "收费公路" '{"公路名称": "沪宁高速公路", "公路编码": "G42", "起始桩号": "K0+000", "终止桩号": "K274+000"}' "公路名称"
create_instance "收费公路" '{"公路名称": "沪杭高速公路", "公路编码": "G60", "起始桩号": "K0+000", "终止桩号": "K151+000"}' "公路名称"

echo "步骤 3: 创建收费站"
create_instance "收费站" '{"收费站名称": "南京收费站", "收费站编码": "NJ001", "桩号": "K0+500"}' "收费站名称"
create_instance "收费站" '{"收费站名称": "上海收费站", "收费站编码": "SH001", "桩号": "K274+000"}' "收费站名称"
create_instance "收费站" '{"收费站名称": "杭州收费站", "收费站编码": "HZ001", "桩号": "K151+000"}' "收费站名称"

echo "步骤 4: 创建ETC门架"
create_instance "ETC门架" '{"门架名称": "沪宁高速K50门架", "门架编码": "G42-K50", "桩号": "K50+000"}' "门架名称"
create_instance "ETC门架" '{"门架名称": "沪宁高速K150门架", "门架编码": "G42-K150", "桩号": "K150+000"}' "门架名称"
create_instance "ETC门架" '{"门架名称": "沪杭高速K75门架", "门架编码": "G60-K75", "桩号": "K75+000"}' "门架名称"

echo "步骤 5: 创建收费单元"
create_instance "收费单元" '{"单元名称": "南京-镇江段", "单元编码": "NJ-ZJ", "里程": 65.5}' "单元名称"
create_instance "收费单元" '{"单元名称": "镇江-常州段", "单元编码": "ZJ-CZ", "里程": 68.2}' "单元名称"
create_instance "收费单元" '{"单元名称": "上海-嘉兴段", "单元编码": "SH-JX", "里程": 75.8}' "单元名称"

echo "步骤 6: 创建车道"
create_instance "车道" '{"车道编号": "NJ001-01", "车道类型": "ETC"}' "车道编号"
create_instance "车道" '{"车道编号": "NJ001-02", "车道类型": "MTC"}' "车道编号"
create_instance "车道" '{"车道编号": "SH001-01", "车道类型": "ETC"}' "车道编号"

echo "步骤 7: 创建标识点"
create_instance "标识点" '{"标识点编码": "G42-K50-001", "标识点类型": "ETC门架", "桩号": "K50+000"}' "标识点编码"
create_instance "标识点" '{"标识点编码": "G42-K150-001", "标识点类型": "ETC门架", "桩号": "K150+000"}' "标识点编码"
create_instance "标识点" '{"标识点编码": "NJ001-01-001", "标识点类型": "车道", "桩号": "K0+500"}' "标识点编码"

echo "步骤 8: 创建车辆"
create_instance "车辆" '{"车牌号": "苏A12345", "车辆类型": "小型客车", "车主姓名": "张三"}' "车牌号"
create_instance "车辆" '{"车牌号": "沪B67890", "车辆类型": "小型客车", "车主姓名": "李四"}' "车牌号"

echo "步骤 9: 创建通行介质"
create_instance "通行介质" '{"介质编号": "ETC001234567890", "介质类型": "ETC卡", "发行日期": "2023-01-15"}' "介质编号"
create_instance "通行介质" '{"介质编号": "OBU987654321098", "介质类型": "OBU", "发行日期": "2023-03-20"}' "介质编号"

echo "步骤 10: 创建交易流水"
create_instance "交易流水" '{"交易时间": "2024-12-19T10:30:00Z", "交易金额": 25.50, "交易类型": "ETC扣费"}' "" "交易流水_1"
create_instance "交易流水" '{"交易时间": "2024-12-19T10:35:00Z", "交易金额": 18.20, "交易类型": "ETC扣费"}' "" "交易流水_2"
create_instance "交易流水" '{"交易时间": "2024-12-19T11:00:00Z", "交易金额": 32.80, "交易类型": "MTC收费"}' "" "交易流水_3"

echo "步骤 11: 创建车辆通行路径"
create_instance "车辆通行路径" '{"通行开始时间": "2024-12-19T10:00:00Z", "通行结束时间": "2024-12-19T11:30:00Z", "通行状态": "已完成"}' "" "车辆通行路径_1"
create_instance "车辆通行路径" '{"通行开始时间": "2024-12-19T14:00:00Z", "通行结束时间": "2024-12-19T15:20:00Z", "通行状态": "已完成"}' "" "车辆通行路径_2"

echo "步骤 12: 创建通行拟合路径"
create_instance "通行拟合路径" '{"拟合时间": "2024-12-19T11:35:00Z", "拟合状态": "成功", "总里程": 274.0}' "" "通行拟合路径_1"
create_instance "通行拟合路径" '{"拟合时间": "2024-12-19T15:25:00Z", "拟合状态": "成功", "总里程": 151.0}' "" "通行拟合路径_2"

echo "步骤 13: 创建拆分明细"
create_instance "拆分明细" '{"拆分金额": 12.75, "拆分比例": 0.5, "拆分时间": "2024-12-19T11:40:00Z"}' "" "拆分明细_1"
create_instance "拆分明细" '{"拆分金额": 12.75, "拆分比例": 0.5, "拆分时间": "2024-12-19T11:40:00Z"}' "" "拆分明细_2"
create_instance "拆分明细" '{"拆分金额": 9.10, "拆分比例": 0.5, "拆分时间": "2024-12-19T11:40:00Z"}' "" "拆分明细_3"

echo "=========================================="
echo "创建关系"
echo "=========================================="
echo ""

echo "创建管理关系"
create_link "管理" "路段业主_江苏交通控股有限公司" "收费公路_沪宁高速公路" ""
create_link "管理" "路段业主_浙江交通投资集团" "收费公路_沪杭高速公路" ""

echo "创建包含关系"
create_link "包含收费站" "收费公路_沪宁高速公路" "收费站_南京收费站" ""
create_link "包含收费站" "收费公路_沪宁高速公路" "收费站_上海收费站" ""
create_link "包含收费站" "收费公路_沪杭高速公路" "收费站_杭州收费站" ""

create_link "包含ETC门架" "收费公路_沪宁高速公路" "ETC门架_沪宁高速K50门架" ""
create_link "包含ETC门架" "收费公路_沪宁高速公路" "ETC门架_沪宁高速K150门架" ""
create_link "包含ETC门架" "收费公路_沪杭高速公路" "ETC门架_沪杭高速K75门架" ""

create_link "包含收费单元" "收费公路_沪宁高速公路" "收费单元_南京-镇江段" ""
create_link "包含收费单元" "收费公路_沪宁高速公路" "收费单元_镇江-常州段" ""
create_link "包含收费单元" "收费公路_沪杭高速公路" "收费单元_上海-嘉兴段" ""

create_link "包含车道" "收费站_南京收费站" "车道_NJ001-01" ""
create_link "包含车道" "收费站_南京收费站" "车道_NJ001-02" ""
create_link "包含车道" "收费站_上海收费站" "车道_SH001-01" ""

create_link "代收" "ETC门架_沪宁高速K50门架" "收费单元_南京-镇江段" ""
create_link "代收" "ETC门架_沪宁高速K150门架" "收费单元_镇江-常州段" ""

echo "创建继承关系"
create_link "继承标识点_ETC门架" "ETC门架_沪宁高速K50门架" "标识点_G42-K50-001" ""
create_link "继承标识点_ETC门架" "ETC门架_沪宁高速K150门架" "标识点_G42-K150-001" ""
create_link "继承标识点_车道" "车道_NJ001-01" "标识点_NJ001-01-001" ""

echo "创建持有关系"
create_link "持有" "车辆_苏A12345" "通行介质_ETC001234567890" '{"绑定时间": "2023-01-20T10:00:00Z", "绑定状态": "有效"}'
create_link "持有" "车辆_沪B67890" "通行介质_OBU987654321098" '{"绑定时间": "2023-03-25T14:00:00Z", "绑定状态": "有效"}'

echo "创建生成关系"
create_link "生成" "标识点_G42-K50-001" "交易流水_1" '{"生成时间": "2024-12-19T10:30:00Z"}'
create_link "生成" "标识点_G42-K150-001" "交易流水_2" '{"生成时间": "2024-12-19T10:35:00Z"}'
create_link "生成" "标识点_NJ001-01-001" "交易流水_3" '{"生成时间": "2024-12-19T11:00:00Z"}'

echo "创建关联交易关系"
create_link "关联交易" "车辆_苏A12345" "交易流水_1" ""
create_link "关联交易" "车辆_苏A12345" "交易流水_2" ""
create_link "关联交易" "车辆_沪B67890" "交易流水_3" ""

echo "创建汇聚为关系"
create_link "汇聚为" "交易流水_1" "车辆通行路径_1" ""
create_link "汇聚为" "交易流水_2" "车辆通行路径_1" ""
create_link "汇聚为" "交易流水_3" "车辆通行路径_2" ""

echo "创建拟合为关系"
create_link "拟合为" "车辆通行路径_1" "通行拟合路径_1" '{"拟合时间": "2024-12-19T11:35:00Z"}'
create_link "拟合为" "车辆通行路径_2" "通行拟合路径_2" '{"拟合时间": "2024-12-19T15:25:00Z"}'

echo "创建拆分为关系"
create_link "拆分为" "通行拟合路径_1" "拆分明细_1" ""
create_link "拆分为" "通行拟合路径_1" "拆分明细_2" ""
create_link "拆分为" "通行拟合路径_2" "拆分明细_3" ""

echo "创建关联拆分明细关系"
create_link "关联拆分明细" "收费单元_南京-镇江段" "拆分明细_1" ""
create_link "关联拆分明细" "收费单元_镇江-常州段" "拆分明细_2" ""
create_link "关联拆分明细" "收费单元_上海-嘉兴段" "拆分明细_3" ""

echo "=========================================="
echo "测试数据创建完成！"
echo "=========================================="
echo ""
echo "创建的实体："
echo "  - 路段业主: 2个"
echo "  - 收费公路: 2个"
echo "  - 收费站: 3个"
echo "  - ETC门架: 3个"
echo "  - 收费单元: 3个"
echo "  - 车道: 3个"
echo "  - 标识点: 3个"
echo "  - 车辆: 2个"
echo "  - 通行介质: 2个"
echo "  - 交易流水: 3个"
echo "  - 车辆通行路径: 2个"
echo "  - 通行拟合路径: 2个"
echo "  - 拆分明细: 3个"
echo ""
echo "创建的关系："
echo "  - 管理: 2个"
echo "  - 包含关系: 9个"
echo "  - 代收: 2个"
echo "  - 继承: 3个"
echo "  - 持有: 2个"
echo "  - 生成: 3个"
echo "  - 关联交易: 3个"
echo "  - 汇聚为: 3个"
echo "  - 拟合为: 2个"
echo "  - 拆分为: 3个"
echo "  - 关联拆分明细: 3个"
echo ""

