#!/usr/bin/env python3
"""
批量训练所有 EPCTL 数据集
增量式训练，每个数据集的样本都会累加到训练集中
"""
import sys
import subprocess
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def train_all_datasets():
    """训练所有数据集"""
    
    # 数据集目录
    dataset_dir = Path(__file__).parent.parent.parent / "脑电数据集"
    
    if not dataset_dir.exists():
        logger.error(f"数据集目录不存在: {dataset_dir}")
        return False
    
    # 获取所有 zip 文件
    zip_files = sorted(dataset_dir.glob("EPCTL*.zip"))
    
    # 过滤掉重复的 EPCTL01
    unique_files = {}
    for zf in zip_files:
        # 提取数字部分 (例如 EPCTL01)
        name_parts = zf.stem.split('-')[0]  # EPCTL01-2025 -> EPCTL01
        if name_parts not in unique_files:
            unique_files[name_parts] = zf
    
    sorted_files = sorted(unique_files.values(), key=lambda x: x.stem)
    
    logger.info(f"找到 {len(sorted_files)} 个数据集")
    for zf in sorted_files:
        logger.info(f"  - {zf.name}")
    
    # EPCTL01 已经训练过，从 EPCTL02 开始
    trained_datasets = ["EPCTL01"]
    
    logger.info(f"\n已训练的数据集: {', '.join(trained_datasets)}")
    
    # 需要训练的数据集
    to_train = [zf for zf in sorted_files if zf.stem.split('-')[0] not in trained_datasets]
    
    if not to_train:
        logger.info("\n所有数据集都已训练完成！")
        return True
    
    logger.info(f"\n待训练数据集: {len(to_train)} 个")
    
    # 训练每个数据集
    success_count = 0
    failed = []
    
    for i, zip_file in enumerate(to_train, 1):
        dataset_name = zip_file.stem.split('-')[0]
        logger.info(f"\n{'='*60}")
        logger.info(f"[{i}/{len(to_train)}] 训练数据集: {dataset_name}")
        logger.info(f"{'='*60}")
        
        # 解压数据集到临时目录
        extract_dir = dataset_dir / f"{dataset_name}_extracted"
        
        try:
            # 解压
            if not extract_dir.exists():
                logger.info(f"解压 {zip_file.name}...")
                subprocess.run([
                    "unzip", "-q", str(zip_file), "-d", str(extract_dir)
                ], check=True)
            
            # 查找 EDF 文件
            edf_files = list(extract_dir.rglob("*PSG.edf"))
            hypnogram_files = list(extract_dir.rglob("*Hypnogram.edf"))
            
            if not edf_files or not hypnogram_files:
                logger.warning(f"  未找到 EDF 文件，跳过")
                failed.append(dataset_name)
                continue
            
            edf_file = edf_files[0]
            hypnogram_file = hypnogram_files[0]
            
            logger.info(f"  EDF: {edf_file.name}")
            logger.info(f"  Hypnogram: {hypnogram_file.name}")
            
            # 运行训练脚本（增量训练）
            logger.info(f"  开始训练...")
            result = subprocess.run([
                sys.executable,
                "src/anphy_sleep/cli.py",
                "train",
                "--edf", str(edf_file),
                "--hypnogram", str(hypnogram_file),
                "--output-dir", "results/models",
                "--incremental"  # 增量训练模式
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"  ✓ {dataset_name} 训练成功")
                success_count += 1
            else:
                logger.error(f"  ✗ {dataset_name} 训练失败")
                logger.error(f"  错误: {result.stderr}")
                failed.append(dataset_name)
            
        except Exception as e:
            logger.error(f"  ✗ 处理 {dataset_name} 时出错: {e}")
            failed.append(dataset_name)
    
    # 训练总结
    logger.info(f"\n{'='*60}")
    logger.info(f"训练完成总结")
    logger.info(f"{'='*60}")
    logger.info(f"成功: {success_count}/{len(to_train)}")
    if failed:
        logger.info(f"失败: {', '.join(failed)}")
    else:
        logger.info(f"所有数据集训练成功！")
    
    return len(failed) == 0


if __name__ == "__main__":
    success = train_all_datasets()
    sys.exit(0 if success else 1)
#!/usr/bin/env python3
"""
批量训练所有 EPCTL 数据集 - 简化版
直接提取 EDF 数据并增量训练
"""
import numpy as np
import mne
from pathlib import Path
from scipy.signal import butter, filtfilt, iirnotch
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import classification_report, accuracy_score
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


def extract_features(eeg_data, sfreq):
    """提取脑电特征（频段功率）"""
    from scipy.signal import welch
    
    # 频段定义
    bands = {
        'delta': (0.5, 4),
        'theta': (4, 8),
        'alpha': (8, 13),
        'beta': (13, 30)
    }
    
    features = []
    
    for ch_idx in range(eeg_data.shape[0]):
        # 计算功率谱密度
        freqs, psd = welch(eeg_data[ch_idx], fs=sfreq, nperseg=int(sfreq * 4))
        
        # 提取每个频段的功率
        for band_name, (low, high) in bands.items():
            mask = (freqs >= low) & (freqs <= high)
            band_power = np.mean(psd[mask])
            features.append(np.log10(band_power + 1e-10))  # 对数变换
    
    # 计算全局平均
    for band_name, (low, high) in bands.items():
        band_powers = []
        for ch_idx in range(eeg_data.shape[0]):
            freqs, psd = welch(eeg_data[ch_idx], fs=sfreq, nperseg=int(sfreq * 4))
            mask = (freqs >= low) & (freqs <= high)
            band_powers.append(np.mean(psd[mask]))
        features.append(np.log10(np.mean(band_powers) + 1e-10))
    
    return np.array(features)


def load_and_process_dataset(edf_path, hypnogram_path):
    """加载并处理一个数据集"""
    logger.info(f"  加载 EDF: {edf_path.name}")
    
    # 读取 EDF
    raw = mne.io.read_raw_edf(str(edf_path), preload=True, verbose=False)
    
    # 读取睡眠分期标注
    annotations = mne.read_annotations(str(hypnogram_path))
    raw.set_annotations(annotations)
    
    # 选择 EEG 通道（16通道标准布局）
    target_channels = ['EEG Fpz-Cz', 'EEG Pz-Oz']  # 常见的睡眠 EEG 通道
    available_channels = [ch for ch in target_channels if ch in raw.ch_names]
    
    if not available_channels:
        # 尝试其他通道名称
        available_channels = [ch for ch in raw.ch_names if 'EEG' in ch.upper()][:2]
    
    if len(available_channels) < 2:
        logger.warning(f"  通道数不足，跳过")
        return None, None
    
    raw.pick_channels(available_channels)
    
    # 滤波：0.5-50 Hz
    raw.filter(0.5, 50.0, fir_design='firwin', verbose=False)
    
    # 50 Hz 陷波滤波
    raw.notch_filter(50.0, fir_design='firwin', verbose=False)
    
    # 分割成 30 秒 epochs
    events, event_id = mne.events_from_annotations(raw, verbose=False)
    
    # 提取特征和标签
    X_list = []
    y_list = []
    
    # 30秒窗口
    window_samples = int(30 * raw.info['sfreq'])
    data = raw.get_data()
    
    for start_sample in range(0, data.shape[1] - window_samples, window_samples):
        window_data = data[:, start_sample:start_sample + window_samples]
        
        # 获取该窗口的睡眠分期标签
        window_time = start_sample / raw.info['sfreq']
        
        # 查找对应的标注
        stage = None
        for ann in raw.annotations:
            if ann['onset'] <= window_time < ann['onset'] + ann['duration']:
                stage_str = ann['description']
                # 映射睡眠分期
                if 'W' in stage_str or 'Wake' in stage_str:
                    stage = 0  # W
                elif 'N1' in stage_str or 'Stage 1' in stage_str:
                    stage = 1  # N1
                elif 'N2' in stage_str or 'Stage 2' in stage_str:
                    stage = 2  # N2
                break
        
        if stage is not None:
            features = extract_features(window_data, raw.info['sfreq'])
            X_list.append(features)
            y_list.append(stage)
    
    if len(X_list) == 0:
        logger.warning(f"  未提取到有效样本")
        return None, None
    
    X = np.array(X_list)
    y = np.array(y_list)
    
    logger.info(f"  提取 {len(X)} 个样本: W={np.sum(y==0)}, N1={np.sum(y==1)}, N2={np.sum(y==2)}")
    
    return X, y


def train_incremental():
    """增量训练所有数据集"""
    
    dataset_dir = Path(__file__).parent.parent.parent / "脑电数据集"
    model_path = Path(__file__).parent / "results" / "models" / "sleep_state_logistic_30s.joblib"
    
    # 获取所有数据集
    zip_files = sorted(dataset_dir.glob("EPCTL*.zip"))
    
    # 去重
    unique_files = {}
    for zf in zip_files:
        name_parts = zf.stem.split('-')[0]
        if name_parts not in unique_files:
            unique_files[name_parts] = zf
    
    sorted_files = sorted(unique_files.values(), key=lambda x: x.stem)
    
    logger.info(f"找到 {len(sorted_files)} 个数据集")
    
    # 累积所有数据
    all_X = []
    all_y = []
    
    trained_count = 0
    
    for i, zip_file in enumerate(sorted_files, 1):
        dataset_name = zip_file.stem.split('-')[0]
        logger.info(f"\n[{i}/{len(sorted_files)}] 处理 {dataset_name}")
        
        # 解压
        extract_dir = dataset_dir / f"{dataset_name}_extracted"
        
        if not extract_dir.exists():
            logger.info(f"  解压...")
            import zipfile
            with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        
        # 查找 EDF 文件
        edf_files = list(extract_dir.rglob("*PSG.edf"))
        hypnogram_files = list(extract_dir.rglob("*Hypnogram.edf"))
        
        if not edf_files or not hypnogram_files:
            logger.warning(f"  未找到 EDF 文件，跳过")
            continue
        
        try:
            X, y = load_and_process_dataset(edf_files[0], hypnogram_files[0])
            
            if X is not None:
                all_X.append(X)
                all_y.append(y)
                trained_count += 1
        except Exception as e:
            logger.error(f"  处理失败: {e}")
            continue
    
    if trained_count == 0:
        logger.error("没有成功处理的数据集")
        return False
    
    # 合并所有数据
    logger.info(f"\n合并 {trained_count} 个数据集的数据...")
    X_all = np.vstack(all_X)
    y_all = np.hstack(all_y)
    
    logger.info(f"总样本数: {len(X_all)}")
    logger.info(f"类别分布: W={np.sum(y_all==0)}, N1={np.sum(y_all==1)}, N2={np.sum(y_all==2)}")
    
    # 训练模型
    logger.info("\n开始训练模型...")
    
    model = Pipeline([
        ('scaler', StandardScaler()),
        ('model', LogisticRegression(
            class_weight='balanced',
            max_iter=1000,
            random_state=42
        ))
    ])
    
    model.fit(X_all, y_all)
    
    # 评估
    y_pred = model.predict(X_all)
    accuracy = accuracy_score(y_all, y_pred)
    
    logger.info(f"\n训练集准确率: {accuracy:.4f}")
    logger.info("\n分类报告:")
    logger.info(classification_report(y_all, y_pred, target_names=['W', 'N1', 'N2']))
    
    # 保存模型（正确格式）
    channels = ['Fp1', 'Fp2', 'F3', 'F4', 'F7', 'F8', 'Fz', 'C3', 'C4', 'Cz', 'T7', 'T8', 'P3', 'P4', 'O1', 'O2']
    bands = ['delta', 'theta', 'alpha', 'beta']
    
    features = []
    for ch in channels:
        for band in bands:
            features.append(f"{ch}_{band}")
    for band in bands:
        features.append(f"avg_{band}")
    
    model_bundle = {
        "model": model,
        "features": features,
        "classes": ['W', 'N1', 'N2'],
        "aggregation_seconds": 30.0
    }
    
    model_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 备份旧模型
    if model_path.exists():
        import shutil
        backup_path = model_path.with_suffix('.joblib.backup_before_full_training')
        shutil.copy2(model_path, backup_path)
        logger.info(f"已备份旧模型: {backup_path.name}")
    
    joblib.dump(model_bundle, model_path)
    logger.info(f"\n✓ 模型已保存: {model_path}")
    logger.info(f"  训练数据集数量: {trained_count}")
    logger.info(f"  总样本数: {len(X_all)}")
    logger.info(f"  准确率: {accuracy:.4f}")
    
    return True


if __name__ == "__main__":
    import sys
    success = train_incremental()
    sys.exit(0 if success else 1)
