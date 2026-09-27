#!/usr/bin/env python3
"""
修复模型格式以匹配推理引擎要求
"""
import joblib
import pickle
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_model_bundle(input_path: str, output_path: str):
    """
    将旧格式模型转换为推理引擎要求的格式
    
    推理引擎要求的格式:
    {
        "model": sklearn_pipeline,
        "features": list[str],
        "classes": list[str],
        "aggregation_seconds": float (optional)
    }
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    logger.info(f"读取模型: {input_path}")
    
    # 尝试加载现有模型
    try:
        bundle = joblib.load(input_path)
        logger.info(f"加载的数据类型: {type(bundle)}")
        
        if isinstance(bundle, dict):
            logger.info(f"字典键: {list(bundle.keys())}")
        
    except Exception as e:
        logger.error(f"joblib 加载失败: {e}")
        # 尝试用 pickle
        try:
            with open(input_path, 'rb') as f:
                bundle = pickle.load(f)
            logger.info(f"用 pickle 加载成功，类型: {type(bundle)}")
        except Exception as e2:
            logger.error(f"pickle 也加载失败: {e2}")
            return False
    
    # 16通道特征名称（与训练数据匹配）
    channels = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'Fz', 'C3', 'C4', 'Cz', 'T7', 'T8', 'P3', 'P4', 'O1', 'O2']
    bands = ['delta', 'theta', 'alpha', 'beta']
    
    # 生成特征名称列表（每个通道的每个频段 + 平均值）
    features = []
    for ch in channels:
        for band in bands:
            features.append(f"{ch}_{band}")
    
    # 添加全局平均特征
    for band in bands:
        features.append(f"avg_{band}")
    
    # 睡眠状态类别
    classes = ['W', 'N1', 'N2']
    
    # 构建正确格式的 bundle
    if isinstance(bundle, dict):
        # 如果已经是字典，补充缺失的键
        model = bundle.get('model')
        if model is None:
            logger.error("字典中没有 'model' 键")
            return False
        
        new_bundle = {
            "model": model,
            "features": features,
            "classes": classes,
            "aggregation_seconds": 30.0
        }
    else:
        # 如果是直接的模型对象
        new_bundle = {
            "model": bundle,
            "features": features,
            "classes": classes,
            "aggregation_seconds": 30.0
        }
    
    # 保存新格式
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(new_bundle, output_path)
    logger.info(f"✓ 已保存修复后的模型到: {output_path}")
    
    # 验证
    logger.info("验证新模型...")
    verify_bundle = joblib.load(output_path)
    logger.info(f"  - 键: {list(verify_bundle.keys())}")
    logger.info(f"  - 特征数量: {len(verify_bundle['features'])}")
    logger.info(f"  - 类别: {verify_bundle['classes']}")
    logger.info(f"  - 聚合时间: {verify_bundle.get('aggregation_seconds', 'N/A')} 秒")
    
    return True


if __name__ == "__main__":
    import sys
    
    # 修复睡眠状态分类模型
    model_dir = Path(__file__).parent / "results" / "models"
    
    old_model = model_dir / "sleep_state_logistic_30s.joblib"
    new_model = model_dir / "sleep_state_logistic_30s_fixed.joblib"
    
    if not old_model.exists():
        logger.error(f"模型文件不存在: {old_model}")
        sys.exit(1)
    
    success = fix_model_bundle(old_model, new_model)
    
    if success:
        # 备份旧模型
        backup = model_dir / "sleep_state_logistic_30s.joblib.backup"
        import shutil
        shutil.copy2(old_model, backup)
        logger.info(f"✓ 已备份旧模型到: {backup}")
        
        # 替换旧模型
        shutil.copy2(new_model, old_model)
        logger.info(f"✓ 已替换原模型文件")
        
        logger.info("\n✅ 模型格式修复完成！")
    else:
        logger.error("\n❌ 模型格式修复失败")
        sys.exit(1)
