-- ============================================
-- MyPalantir H2 数据库初始化脚本（宽表版本）
-- 将 toll_stations、vehicles、toll_records 三张表合并为一张宽表
-- 根据 ontology/schema.yaml 定义生成
-- ============================================

-- ============================================
-- 1. 创建宽表（合并收费站、车辆、收费记录）
-- ============================================

CREATE TABLE IF NOT EXISTS toll_records_wide (
    -- 收费记录字段
    record_id VARCHAR(50) PRIMARY KEY,
    amount DECIMAL(10, 2) NOT NULL COMMENT '收费金额',
    charge_time TIMESTAMP NOT NULL COMMENT '收费时间',
    
    -- 收费站字段
    station_id VARCHAR(50) NOT NULL COMMENT '收费站ID',
    station_name VARCHAR(100) NOT NULL COMMENT '收费站名称',
    station_province VARCHAR(50) NOT NULL COMMENT '所属省份',
    
    -- 车辆字段
    vehicle_id VARCHAR(50) NOT NULL COMMENT '车辆ID',
    plate_number VARCHAR(20) NOT NULL COMMENT '车牌号',
    vehicle_type VARCHAR(50) COMMENT '车辆类型',
    owner_name VARCHAR(100) COMMENT '车主姓名',
    
    -- 时间戳字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ============================================
-- 2. 创建通行介质表（保留，因为不在合并范围内）
-- ============================================

CREATE TABLE IF NOT EXISTS media (
    media_id VARCHAR(50) PRIMARY KEY,
    media_number VARCHAR(50) NOT NULL UNIQUE COMMENT '介质编号',
    media_type VARCHAR(50) NOT NULL COMMENT '介质类型（ETC卡、OBU等）',
    issue_date DATE COMMENT '发行日期',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ============================================
-- 3. 创建车辆-通行介质关联表（保留，因为不在合并范围内）
-- ============================================

CREATE TABLE IF NOT EXISTS vehicle_media (
    link_id VARCHAR(50) PRIMARY KEY,
    vehicle_id VARCHAR(50) NOT NULL COMMENT '车辆ID（逻辑关联，无外键约束）',
    media_id VARCHAR(50) NOT NULL COMMENT '通行介质ID',
    bind_time TIMESTAMP COMMENT '绑定时间（对应 link type 的"绑定时间"属性）',
    bind_status VARCHAR(50) COMMENT '绑定状态（对应 link type 的"绑定状态"属性）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_vm_media FOREIGN KEY (media_id) REFERENCES media(media_id) ON DELETE CASCADE,
    CONSTRAINT uk_vm_vehicle_media UNIQUE (vehicle_id, media_id)
);

-- ============================================
-- 4. 创建索引
-- ============================================

CREATE INDEX IF NOT EXISTS idx_toll_records_wide_station_id ON toll_records_wide(station_id);
CREATE INDEX IF NOT EXISTS idx_toll_records_wide_station_province ON toll_records_wide(station_province);
CREATE INDEX IF NOT EXISTS idx_toll_records_wide_vehicle_id ON toll_records_wide(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_toll_records_wide_plate_number ON toll_records_wide(plate_number);
CREATE INDEX IF NOT EXISTS idx_toll_records_wide_charge_time ON toll_records_wide(charge_time);
CREATE INDEX IF NOT EXISTS idx_media_number ON media(media_number);
CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);
CREATE INDEX IF NOT EXISTS idx_vehicle_media_vehicle_id ON vehicle_media(vehicle_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_media_media_id ON vehicle_media(media_id);

-- ============================================
-- 5. 插入测试数据
-- ============================================

-- 插入通行介质数据（8个通行介质）
INSERT INTO media (media_id, media_number, media_type, issue_date) VALUES
('MED001', 'OBU-2024-001', 'OBU', '2024-01-15'),
('MED002', 'OBU-2024-002', 'OBU', '2024-02-20'),
('MED003', 'OBU-2024-003', 'OBU', '2024-03-10'),
('MED004', 'OBU-2024-004', 'OBU', '2024-04-05'),
('MED005', 'ETC-2024-001', 'ETC卡', '2024-01-10'),
('MED006', 'ETC-2024-002', 'ETC卡', '2024-02-15'),
('MED007', 'ETC-2024-003', 'ETC卡', '2024-03-20'),
('MED008', 'ETC-2024-004', 'ETC卡', '2024-04-25');

-- 插入车辆-通行介质关联数据（"持有"关系，关系表模式）
INSERT INTO vehicle_media (link_id, vehicle_id, media_id, bind_time, bind_status) VALUES
('LINK001', 'VEH001', 'MED001', '2024-01-20 10:00:00', '已激活'),
('LINK002', 'VEH001', 'MED005', '2024-01-25 14:30:00', '已激活'),
('LINK003', 'VEH002', 'MED002', '2024-02-25 09:15:00', '已激活'),
('LINK004', 'VEH003', 'MED003', '2024-03-15 11:20:00', '已激活'),
('LINK005', 'VEH004', 'MED004', '2024-04-10 16:45:00', '已激活'),
('LINK006', 'VEH005', 'MED006', '2024-05-18 08:30:00', '已激活'),
('LINK007', 'VEH005', 'MED007', '2024-05-20 13:00:00', '已激活'),
('LINK008', 'VEH006', 'MED008', '2024-03-25 15:30:00', '已激活');

-- 插入宽表数据（合并收费站、车辆、收费记录）
-- 南京收费站 (ST001) - 8条记录
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC001', 'ST001', '南京收费站', '江苏', 'VEH001', '苏A11111', '小型客车', '张三', 25.50, '2024-01-05 08:30:00'),
('REC002', 'ST001', '南京收费站', '江苏', 'VEH002', '苏B22222', '小型客车', '李四', 30.00, '2024-01-05 09:15:00'),
('REC003', 'ST001', '南京收费站', '江苏', 'VEH003', '苏C33333', '大型客车', '王五', 45.00, '2024-01-10 10:20:00'),
('REC004', 'ST001', '南京收费站', '江苏', 'VEH004', '苏D44444', '小型货车', '赵六', 35.50, '2024-01-15 14:30:00'),
('REC005', 'ST001', '南京收费站', '江苏', 'VEH005', '苏E55555', '小型客车', '钱七', 28.00, '2024-01-20 16:45:00'),
('REC006', 'ST001', '南京收费站', '江苏', 'VEH001', '苏A11111', '小型客车', '张三', 25.50, '2024-01-25 11:00:00'),
('REC007', 'ST001', '南京收费站', '江苏', 'VEH006', '苏F66666', '小型客车', '孙八', 32.00, '2024-01-28 13:20:00'),
('REC008', 'ST001', '南京收费站', '江苏', 'VEH007', '苏G77777', '小型客车', '周九', 29.50, '2024-01-30 15:10:00');

-- 苏州收费站 (ST002) - 6条记录
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC009', 'ST002', '苏州收费站', '江苏', 'VEH001', '苏A11111', '小型客车', '张三', 40.00, '2024-01-08 09:00:00'),
('REC010', 'ST002', '苏州收费站', '江苏', 'VEH002', '苏B22222', '小型客车', '李四', 42.50, '2024-01-12 10:30:00'),
('REC011', 'ST002', '苏州收费站', '江苏', 'VEH003', '苏C33333', '大型客车', '王五', 60.00, '2024-01-18 12:15:00'),
('REC012', 'ST002', '苏州收费站', '江苏', 'VEH005', '苏E55555', '小型客车', '钱七', 38.00, '2024-01-22 14:00:00'),
('REC013', 'ST002', '苏州收费站', '江苏', 'VEH006', '苏F66666', '小型客车', '孙八', 45.00, '2024-01-26 16:30:00'),
('REC014', 'ST002', '苏州收费站', '江苏', 'VEH008', '苏H88888', '小型客车', '吴十', 35.00, '2024-01-29 08:45:00');

-- 无锡收费站 (ST003) - 5条记录
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC015', 'ST003', '无锡收费站', '江苏', 'VEH002', '苏B22222', '小型客车', '李四', 35.00, '2024-01-06 07:20:00'),
('REC016', 'ST003', '无锡收费站', '江苏', 'VEH004', '苏D44444', '小型货车', '赵六', 50.00, '2024-01-11 11:40:00'),
('REC017', 'ST003', '无锡收费站', '江苏', 'VEH005', '苏E55555', '小型客车', '钱七', 33.00, '2024-01-16 13:50:00'),
('REC018', 'ST003', '无锡收费站', '江苏', 'VEH007', '苏G77777', '小型客车', '周九', 40.50, '2024-01-24 09:30:00'),
('REC019', 'ST003', '无锡收费站', '江苏', 'VEH008', '苏H88888', '小型客车', '吴十', 36.00, '2024-01-27 15:20:00');

-- 杭州收费站 (ST004) - 1条记录
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC020', 'ST004', '杭州收费站', '浙江', 'VEH009', '浙A99999', '小型客车', '浙江车主', 55.00, '2024-01-10 10:00:00');

-- 上海收费站 (ST005) - 1条记录
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC021', 'ST005', '上海收费站', '上海', 'VEH010', '沪A00000', '小型客车', '上海车主', 48.00, '2024-01-15 12:00:00');

-- 非2024年1月的数据（用于验证时间过滤）
INSERT INTO toll_records_wide (record_id, station_id, station_name, station_province, vehicle_id, plate_number, vehicle_type, owner_name, amount, charge_time) VALUES
('REC022', 'ST001', '南京收费站', '江苏', 'VEH001', '苏A11111', '小型客车', '张三', 25.50, '2023-12-30 08:30:00'),
('REC023', 'ST001', '南京收费站', '江苏', 'VEH002', '苏B22222', '小型客车', '李四', 30.00, '2024-02-01 09:15:00');

-- ============================================
-- 数据验证（注释掉，因为会在 Java 程序中执行）
-- ============================================
-- SELECT '宽表收费记录数据' AS table_name, COUNT(*) AS count FROM toll_records_wide
-- UNION ALL
-- SELECT '通行介质数据', COUNT(*) FROM media
-- UNION ALL
-- SELECT '车辆-通行介质关联数据', COUNT(*) FROM vehicle_media;
