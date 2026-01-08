-- ============================================
-- 电网规划数据 H2 数据库初始化脚本
-- ============================================

CREATE TABLE IF NOT EXISTS energy_base_hundredtenkvpowergrid_plan (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  area VARCHAR(64) NOT NULL DEFAULT '',
  voltage_level VARCHAR(64) NOT NULL DEFAULT '',
  plan_substation_capacity VARCHAR(64) NOT NULL DEFAULT '',
  plan_main_transformer_number VARCHAR(64) NOT NULL DEFAULT '',
  plan_main_transformer_capacity VARCHAR(64) NOT NULL DEFAULT '',
  opt_date VARCHAR(32) NOT NULL DEFAULT '',
  years VARCHAR(32) NOT NULL DEFAULT '',
  "month" VARCHAR(32) NOT NULL DEFAULT '',
  data_source VARCHAR(32) NOT NULL DEFAULT '',
  deal_flag VARCHAR(1) NOT NULL DEFAULT '0',
  delete_flag VARCHAR(1) NOT NULL DEFAULT '0',
  create_id VARCHAR(64) NOT NULL DEFAULT '',
  create_name VARCHAR(128) NOT NULL DEFAULT '',
  create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  modify_id VARCHAR(64) NOT NULL DEFAULT '',
  modify_name VARCHAR(128) NOT NULL DEFAULT '',
  modify_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  plan_length VARCHAR(45) NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_area ON energy_base_hundredtenkvpowergrid_plan(area);
CREATE INDEX IF NOT EXISTS idx_voltage_level ON energy_base_hundredtenkvpowergrid_plan(voltage_level);
CREATE INDEX IF NOT EXISTS idx_opt_date ON energy_base_hundredtenkvpowergrid_plan(opt_date);
CREATE INDEX IF NOT EXISTS idx_years ON energy_base_hundredtenkvpowergrid_plan(years);

INSERT INTO energy_base_hundredtenkvpowergrid_plan (area,voltage_level,plan_substation_capacity,plan_main_transformer_number,plan_main_transformer_capacity,opt_date,years,"month",data_source,deal_flag,delete_flag,create_id,create_name,create_time,modify_id,modify_name,modify_time,plan_length) VALUES 
('全省','110千伏','1651.13','0','8630.97','2021-01','2021','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','110千伏','1317.28','0','8630.97','2022-01','2022','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','110千伏','164.24','0','8630.97','2023-01','2023','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','110千伏','1269.93','0','8630.97','2024-01','2024','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','110千伏','2649.54','0','8630.97','2025-01','2025','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','35千伏','8906.84','0','853.48','2021-01','2021','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','35千伏','5377.16','0','853.48','2022-01','2022','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','35千伏','2015.52','0','853.48','2023-01','2023','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','35千伏','9897.39','0','853.48','2024-01','2024','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000',''),
('全省','35千伏','9907.78','0','853.48','2025-01','2025','01','','0','1','','','2024-09-12 20:12:21.000','njbcs01','测试01','2024-09-30 00:48:40.000','');

INSERT INTO energy_base_hundredtenkvpowergrid_plan (area,voltage_level,plan_substation_capacity,plan_main_transformer_number,plan_main_transformer_capacity,opt_date,years,"month",data_source,deal_flag,delete_flag,create_id,create_name,create_time,modify_id,modify_name,modify_time,plan_length) VALUES 
('全省','110千伏','9161.25','可不填','可不填','2021-01','2021','01','','0','1','','','2024-09-30 00:49:08.000','njbcs01','测试01','2024-09-30 00:49:36.000','8630.97'),
('全省','110千伏','4910.71','','','2022-01','2022','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','8630.97'),
('全省','110千伏','840.29','','','2023-01','2023','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','8630.97'),
('全省','110千伏','1780.03','','','2024-01','2024','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','8630.97'),
('全省','110千伏','6255.03','','','2025-01','2025','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','8630.97'),
('全省','35千伏','2841.32','','','2021-01','2021','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','853.48'),
('全省','35千伏','7688.87','','','2022-01','2022','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','853.48'),
('全省','35千伏','515.64','','','2023-01','2023','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','853.48'),
('全省','35千伏','592.37','','','2024-01','2024','01','','0','0','','','2024-09-30 00:49:08.000','','','2024-09-30 00:49:08.000','853.48'),
('全省','35千伏','6609.2','','','2025-01','2025','01','','0','1','','','2024-09-30 00:49:08.000','njbadmin','能监办','2025-05-24 22:35:28.000','853.48');

INSERT INTO energy_base_hundredtenkvpowergrid_plan (area,voltage_level,plan_substation_capacity,plan_main_transformer_number,plan_main_transformer_capacity,opt_date,years,"month",data_source,deal_flag,delete_flag,create_id,create_name,create_time,modify_id,modify_name,modify_time,plan_length) VALUES 
('全省','110千伏','253.52','','','2021-01','2021','01','','0','0','njbcs01','测试01','2024-09-30 00:49:55.000','','','2024-09-30 00:49:55.000','8630.97'),
('全省','35千伏','5331.1','1','2','2025-01','2025','01','','0','0','njbadmin','能监办','2025-05-24 22:35:29.000','njbadmin','能监办','2025-05-24 22:35:29.000','853.48'),
('1','2','9008.2','','','2025-05','2025','05','','0','1','njbadmin','能监办','2025-05-24 22:45:01.000','njbadmin','能监办','2025-05-24 22:45:05.000','4'),
('1','2','3187.98','','4','2025-05','2025','05','','0','0','njbadmin','能监办','2025-05-27 22:06:05.000','njbadmin','能监办','2025-05-27 22:06:45.000','2');
