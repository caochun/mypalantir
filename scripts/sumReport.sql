//现金汇总
 insert into tbl_managesplitsum (cleardate,  splitorg,  corp,  road,  orgtype, paycardtype, moneyflag, cashsplitmoney, cashopsplitmoney, cashtollmoney, cashoptollmoney, othersplitmoney, otheropsplitmoney, othertollmoney, otheroptollmoney, unionsplitmoney, unionopsplitmoney, uniontollmoney, unionoptollmoney, etcsplitmoney, etcopsplitmoney, etctollmoney, etcoptollmoney, alipaysplitmoney, alipayopsplitmoney, alipaytollmoney, alipayoptollmoney, wepaysplitmoney, wepayopsplitmoney, wepaytollmoney, wepayoptollmoney, cashreturnmoney, otherreturnmoney, unionreturnmoney, alipayreturnmoney, wepayreturnmoney, gentime)  
select nvl(a.ClearDate,b.ClearDate) as ClearDate,//清分日期
(case when a.splitOrg is not null then a.splitOrg  else b.splitOrg end) as SPLITORG,//小业主编码：长度2位-外省编码；长度4位-小业主编码
nvl(a.corp,b.corp) corp,//运营管理单位编码：长度2位-外省编码；长度6位-运营管理单位编码
nvl(a.road,b.road) road,//路段编码：长度2位-外省编码；长度6位-路段编码
1 as orgType,
nvl(a.payCardType,b.payCardType) as payCardType,//支付卡类型，现金交易填0
0 as moneyflag,//0-现金、移动支付
nvl(a.cashsplitmoney,0) as cashSplitMoney,//拆账   现金总收入
nvl(a.cashopsplitmoney,0) as cashopsplitmoney,//拆账  现金外省代收收入
nvl(b.cashtollmoney,0) as cashtollmoney,//通行费   现金总收入
nvl(b.cashoptollmoney,0) as cashoptollmoney,//通行费   现金代外省收收入
nvl(a.othersplitmoney,0) as othersplitmoney,//拆账   其他总收入
nvl(a.otheropsplitmoney,0) as otheropsplitmoney,//拆账  其他外省代收收入
nvl(b.othertollmoney,0) as othertollmoney,//通行费   其他总收入
nvl(b.otheroptollmoney,0) as otheroptollmoney,//通行费   其他代外省收收入
nvl(a.unionsplitmoney,0) as unionsplitmoney,//拆账   银联总收入
nvl(a.unionopsplitmoney,0) as unionopsplitmoney,//拆账 银联外省代收收入
nvl(b.uniontollmoney,0) as uniontollmoney,//通行费   银联总收入
nvl(b.unionoptollmoney,0) as unionoptollmoney,//通行费   银联代外省收收入
0 as etcsplitmoney ,//拆账   ETC总收入
0 as etcopsplitmoney,//拆账  ETC外省代收收入
0 as etctollmoney,//通行费   ETC总收入
0 as etcoptollmoney,//通行费   ETC代外省收收入
nvl(a.alipaysplitmoney,0) as alipaysplitmoney ,//拆账   支付宝总收入
nvl(a.alipayopsplitmoney,0) as alipayopsplitmoney,//拆账  支付宝外省代收收入
nvl(b.alipaytollmoney,0) as alipaytollmoney ,//通行费   支付宝总收入
nvl(b.alipayoptollmoney,0) as alipayoptollmoney,//通行费   支付宝代外省收收入
nvl(a.wepaysplitmoney,0) as wepaysplitmoney ,//拆账   微信总收入
nvl(a.wepayopsplitmoney,0) as wepayopsplitmoney,//拆账  微信外省代收收入
nvl(b.wepaytollmoney,0) as wepaytollmoney ,//通行费   微信总收入
nvl(b.wepayoptollmoney,0) as wepayoptollmoney,//通行费   微信代外省收收入
nvl(b.cashreturnmoney,0) cashreturnmoney,nvl(b.otherreturnmoney,0) otherreturnmoney,nvl(b.unionreturnmoney,0) unionreturnmoney,nvl(b.alipayreturnmoney,0) alipayreturnmoney,nvl(b.wepayreturnmoney,0) wepayreturnmoney,//现金退费
sysdate as gentime //生成时间
from (
select ClearDate,payCardType,case when splitOrg in('2701','2702') then '7215' else splitOrg end splitOrg,case when corp='320000' then '570000' else corp end corp,road,sum(cashsplitmoney) cashsplitmoney,sum(cashopsplitmoney) cashopsplitmoney,  //2025-05-20修改烟威公司下的清分结算数据归属到投资半岛公司（splitOrg in('2701','2702') then '7215'；corp='320000' then '570000'）
sum(othersplitmoney) othersplitmoney,sum(otheropsplitmoney) otheropsplitmoney,sum(unionsplitmoney) unionsplitmoney,sum(unionopsplitmoney) unionopsplitmoney,
sum(alipaysplitmoney) alipaysplitmoney,sum(alipayopsplitmoney) alipayopsplitmoney,sum(wepaysplitmoney) wepaysplitmoney,sum(wepayopsplitmoney) wepayopsplitmoney,
sum(cashreturnmoney) cashreturnmoney,sum(otherreturnmoney) otherreturnmoney,sum(unionreturnmoney) unionreturnmoney,sum(alipayreturnmoney) alipayreturnmoney,sum(wepayreturnmoney) wepayreturnmoney from(
select ClearDate,payCardType,
case when length(tollSectionID)=6 then substr(tollSectionID,1,2) else (select roadid from tbl_gbsectiondic where id=tollSectionID) end splitOrg,//length(tollSectionID)=6——外省通行方编码，截取前两位作为外省省中心编码；length(tollSectionID)!=6——拆分小业主的国标编码，转为小业主的省标
case when length(tollSectionID)=6 then substr(tollSectionID,1,2) else (select bl_road from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=tollSectionID)||'00')||'0000' end road,//length(tollSectionID)=6——外省通行方编码，截取前两位作为外省省中心编码；length(tollSectionID)!=6——根据拆分小业主查询对应的路段
case when length(tollSectionID)=6 then substr(tollSectionID,1,2) else (select bl_corp from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=tollSectionID)||'00')||'0000' end corp,//length(tollSectionID)=6——外省通行方编码，截取前两位作为外省省中心编码；length(tollSectionID)!=6——根据拆分小业主查询对应的运营管理单位
SUM( CASE WHEN payType=1 THEN Amount WHEN payType=0  THEN Amount END) AS cashsplitmoney ,//payType=1——现金；payType=0——外省代收（现金+移动支付）
//+ SUM( CASE WHEN paytype=0 THEN Amount END) AS cashopsplitmoney ,
//+ SUM( CASE WHEN paytype=0 and modifyflag=1 THEN Amount when modifyflag=2 and length(EXTOLLSTATION)=2 and length(tollSectionID)=11 THEN Amount END) AS cashopsplitmoney ,//现金+移动支付的外省代收都放到cashopsplitmoney   外省代收的退费不能用paytype来区分
SUM( CASE WHEN provinceType=2 THEN Amount END) AS cashopsplitmoney ,//现金+移动支付的外省代收都放到cashopsplitmoney   外省代收的退费不能用paytype来区分-------------11-30修改
SUM( CASE WHEN payType=2 THEN Amount END) AS othersplitmoney ,//payType=2——其他
0 AS otheropsplitmoney,//外省代收已放到cashopsplitmoney
SUM( CASE WHEN payType=3 THEN Amount END) AS unionsplitmoney ,//payType=3——银联
0 AS unionopsplitmoney, //外省代收已放到cashopsplitmoney
SUM( CASE WHEN payType=6 THEN Amount END) AS alipaysplitmoney ,//payType=5——支付宝-------------11-30修改
0 AS alipayopsplitmoney,//外省代收已放到cashopsplitmoney
SUM( CASE WHEN payType=7 THEN Amount END) AS wepaysplitmoney ,//payType=6——微信-------------11-30修改
0 AS wepayopsplitmoney,  //外省代收已放到cashopsplitmoney
0 cashreturnmoney,0 otherreturnmoney,0 unionreturnmoney,0 alipayreturnmoney,0 wepayreturnmoney //现金退费
from tbl_exClearResultCash where ClearDate=?  and roadtype=1 //roadtype=1——高速公路
group by tollSectionID,payCardType,ClearDate  
) group by case when splitOrg in('2701','2702') then '7215' else splitOrg end,payCardType,ClearDate,road,case when corp='320000' then '570000' else corp end 
) a  full join (
select ClearDate,payCardType,case when length(splitOrg)=6 then substr(splitOrg,1,2) when splitOrg in('2701','2702') then '7215' else splitOrg end splitOrg,road,case when corp='320000' then '570000' else corp end corp,sum(cashtollmoney) cashtollmoney,sum(cashoptollmoney) cashoptollmoney,sum(othertollmoney) othertollmoney,  
sum(otheroptollmoney) otheroptollmoney,sum(uniontollmoney) uniontollmoney,sum(unionoptollmoney) unionoptollmoney,sum(alipaytollmoney) alipaytollmoney, 
sum(alipayoptollmoney) alipayoptollmoney,sum(wepaytollmoney) wepaytollmoney,sum(wepayoptollmoney) wepayoptollmoney,
sum(cashreturnmoney) cashreturnmoney,sum(otherreturnmoney) otherreturnmoney,sum(unionreturnmoney) unionreturnmoney,sum(alipayreturnmoney) alipayreturnmoney,sum(wepayreturnmoney) wepayreturnmoney from(  
select ClearDate,payCardType, 
case when length(extollstation)=2 then extollstation else (select bl_owner from t_orgcode where orgtype=22 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=(select bl_subcenter from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'00') end splitOrg, //根据extollstation查收费小业主
case when length(extollstation)=2 then extollstation else (select bl_road from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'0000' end road, //根据extollstation查收费路段
case when length(extollstation)=2 then extollstation else (select bl_corp from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+clearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'0000' end corp, //根据extollstation查收费运营管理单位
SUM(CASE WHEN payType=1 THEN Amount WHEN payType=0 THEN Amount END) AS cashtollmoney , 
SUM(CASE WHEN payType=1 AND length(tollSectionID)=6 THEN Amount END) AS cashoptollmoney ,
SUM(CASE WHEN payType=2 THEN Amount END) AS othertollmoney ,//payType=2——其他
SUM(CASE WHEN payType=2 AND length(tollSectionID)=6 THEN Amount END) AS otheroptollmoney ,
SUM(CASE WHEN payType=3 THEN Amount END) AS uniontollmoney ,
SUM(CASE WHEN payType=3 AND length(tollSectionID)=6 THEN Amount END) AS unionoptollmoney, 
SUM(CASE WHEN payType=6 THEN Amount END) AS alipaytollmoney ,
SUM(CASE WHEN payType=6 AND length(tollSectionID)=6 THEN Amount END) AS alipayoptollmoney ,
SUM(CASE WHEN payType=7 THEN Amount END) AS wepaytollmoney ,
SUM(CASE WHEN payType=7 AND length(tollSectionID)=6 THEN Amount END) AS wepayoptollmoney, 
SUM(CASE WHEN payType=1 and modifyflag=2 and provinceType=1 AND length(tollSectionID)=6 THEN -Amount END) cashreturnmoney,//现金退费
SUM(CASE WHEN payType=2 and modifyflag=2 and provinceType=1 AND length(tollSectionID)=6 THEN -Amount END) otherreturnmoney,//其他退费
SUM(CASE WHEN payType=3 and modifyflag=2 and provinceType=1 AND length(tollSectionID)=6 THEN -Amount END) unionreturnmoney,//银联退费
SUM(CASE WHEN payType=6 and modifyflag=2 and provinceType=1 AND length(tollSectionID)=6 THEN -Amount END) alipayreturnmoney,//支付宝退费
SUM(CASE WHEN payType=7 and modifyflag=2 and provinceType=1 AND length(tollSectionID)=6 THEN -Amount END) wepayreturnmoney //微信退费
from tbl_exClearResultCash  where ClearDate=?  and roadtype=1 
group by sectionId,payCardType,ClearDate,TOLLSTATION,extollstation) 
group by case when length(splitOrg)=6 then substr(splitOrg,1,2) when splitOrg in('2701','2702') then '7215' else splitOrg end,payCardType,ClearDate,road,case when corp='320000' then '570000' else corp end    
) b  on a.splitOrg=b.splitOrg and a.payCardType=b.payCardType and a.ClearDate=b.ClearDate and a.road=b.road and a.corp=b.corp;
		


//ETC汇总
 insert into tbl_managesplitsum (cleardate, splitorg, corp,  road,orgtype, paycardtype, moneyflag, cashsplitmoney, cashopsplitmoney, cashtollmoney, cashoptollmoney, othersplitmoney, otheropsplitmoney, othertollmoney, otheroptollmoney, unionsplitmoney, unionopsplitmoney, uniontollmoney, unionoptollmoney, etcsplitmoney, etcopsplitmoney, etctollmoney, etcoptollmoney, alipaysplitmoney, alipayopsplitmoney, alipaytollmoney, alipayoptollmoney, wepaysplitmoney, wepayopsplitmoney, wepaytollmoney, wepayoptollmoney, gentime)  
select ClearDate,SPLITORG,corp,road,orgType,payCardType,moneyflag,sum(cashSplitMoney) cashSplitMoney,sum(cashopsplitmoney) cashopsplitmoney,sum(cashtollmoney) cashtollmoney,sum(cashoptollmoney) cashoptollmoney,sum(othersplitmoney) othersplitmoney,sum(otheropsplitmoney) otheropsplitmoney,sum(othertollmoney) othertollmoney,sum(otheroptollmoney) otheroptollmoney,sum(unionsplitmoney) unionsplitmoney,sum(unionopsplitmoney) unionopsplitmoney,sum(uniontollmoney) uniontollmoney,sum(unionoptollmoney) unionoptollmoney,sum(etcsplitmoney) etcsplitmoney,sum(etcopsplitmoney) etcopsplitmoney,sum(etctollmoney) etctollmoney,sum(etcoptollmoney) etcoptollmoney,sum(alipaysplitmoney) alipaysplitmoney,sum(alipayopsplitmoney) alipayopsplitmoney,sum(alipaytollmoney) alipaytollmoney,sum(alipayoptollmoney) alipayoptollmoney,sum(wepaysplitmoney) wepaysplitmoney,sum(wepayopsplitmoney) wepayopsplitmoney,sum(wepaytollmoney) wepaytollmoney,sum(wepayoptollmoney) wepayoptollmoney,sysdate as gentime from(
select nvl(a.ClearDate,b.ClearDate) as ClearDate,
(case when a.splitOrg='99' then substr(a.ISSUERID,1,2) when a.splitOrg<>'99' then  a.splitOrg when b.splitOrg='99' then substr(b.ISSUERID,1,2) else b.splitOrg end) as SPLITORG,
nvl(a.corp,b.corp) corp,nvl(a.road,b.road) road,
1 as orgType,
(case when substr(a.ISSUERID,1,2)<>'37' then 0 when substr(b.ISSUERID,1,2)<>'37' then 0 else 1 end) as payCardType,
1 as moneyflag,//1-ETC
0 as cashSplitMoney,
0 as cashopsplitmoney,
0 as cashtollmoney,
0 as cashoptollmoney,
0 as othersplitmoney,
0 as otheropsplitmoney,
0 as othertollmoney,
0 as otheroptollmoney,
0 as unionsplitmoney,
0 as unionopsplitmoney,
0 as uniontollmoney,
0 as unionoptollmoney,
nvl(a.etcsplitmoney,0) as etcsplitmoney ,
0 as etcopsplitmoney,
nvl(b.etctollmoney,0) as etctollmoney,
0 as etcoptollmoney,
0 as alipaysplitmoney ,
0 as alipayopsplitmoney,
0 as alipaytollmoney ,
0 as alipayoptollmoney,
0 as wepaysplitmoney ,
0 as wepayopsplitmoney,
0 as wepaytollmoney ,
0 as wepayoptollmoney 
from (
select ClearDate,payCardType,case when splitOrg in('2701','2702') then '7215' else splitOrg end splitOrg,road,case when corp='320000' then '570000' else corp end corp,issuerid,sum(etcsplitmoney) etcsplitmoney from(   //2025-05-20修改烟威公司下的清分结算数据归属到投资半岛公司（splitOrg in('2701','2702') then '7215'；corp='320000' then '570000'）
select ClearDate,payCardType,
case when length(tollSectionID)=2 then substr(tollSectionID,1,2) else (select roadid from tbl_gbsectiondic where id=tollSectionID) end splitOrg,
case when length(tollSectionID)=2 then substr(tollSectionID,1,2) else (select bl_road from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=tollSectionID)||'00')||'0000' end road,
case when length(tollSectionID)=2 then substr(tollSectionID,1,2) else (select bl_corp from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=tollSectionID)||'00')||'0000' end corp,
issuerid,sum(Amount) etcsplitmoney 
from tbl_ExClearResultETC where ClearDate=? and roadType=1  
group by tollSectionID,payCardType,ClearDate,issuerid ) group by ClearDate,payCardType,case when splitOrg in('2701','2702') then '7215' else splitOrg end,road,case when corp='320000' then '570000' else corp end,issuerid 
) a  full join (
select ClearDate,payCardType,case when splitOrg in('2701','2702') then '7215' else splitOrg end splitOrg,road,case when corp='320000' then '570000' else corp end corp,issuerid,sum(etctollmoney) etctollmoney from( 
select ClearDate,payCardType,
case when length(extollstation)=2 then extollstation when length(extollstation)=1 then (select roadid from tbl_gbsectiondic where id=sectionID) else (select bl_owner from t_orgcode where orgtype=22 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=(select bl_subcenter from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'00') end splitOrg, //length(extollstation)=1时为门架退费，根据国标收费路段查询省标的分中心、路段、业主；否则根据收费站查询查询省标的分中心、路段、业主
case when length(extollstation)=2 then extollstation when length(extollstation)=1 then (select bl_road from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=sectionID)||'00')||'0000' else (select bl_road from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'0000' end road, 
case when length(extollstation)=2 then extollstation when length(extollstation)=1 then (select bl_corp from t_orgcode where orgtype=40 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode = (select roadid from tbl_gbsectiondic where id=sectionID)||'00')||'0000' else (select bl_corp from t_orgcode where orgtype=23 and lastver=(select max(lastver) from t_orgcode where verusetime<to_date('+ClearDate+ 23:59:59','yyyy-MM-dd hh24:mi:ss')) and orgcode=extollstation)||'0000' end corp, 
issuerid,sum(Amount) etctollmoney 
from tbl_ExClearResultETC  where ClearDate=? and roadType=1  
group by sectionId,payCardType,ClearDate,issuerid,extollstation 
) group by ClearDate,payCardType,case when splitOrg in('2701','2702') then '7215' else splitOrg end,road,case when corp='320000' then '570000' else corp end,issuerid 
) b  on a.ClearDate=b.ClearDate and a.payCardType=b.payCardType and a.splitOrg=b.splitOrg and a.road=b.road and a.corp=b.corp and a.ISSUERID=b.ISSUERID 
) group by ClearDate,SPLITORG,corp,road,orgType,payCardType,moneyflag ;