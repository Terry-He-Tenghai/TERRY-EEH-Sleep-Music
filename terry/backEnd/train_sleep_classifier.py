"""
睡眠分期分类器训练脚本
训练 W / N1 / N2 三分类模型
"""
import numpy as np
import pickle
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_sleep_data(data_dir: str):
    """
    加载睡眠EEG数据集
    
    预期数据格式:
    - data_dir/
      - W/  (清醒数据)
        - sample_001.npy
        - sample_002.npy
        ...
      - N1/ (浅睡眠数据)
        - sample_001.npy
        ...
      - N2/ (深睡眠数据)
        - sample_001.npy
        ...
    
    每个 .npy 文件包含特征向量（例如：功率谱特征、时频特征等）
    """
    data_path = Path(data_dir)
    
    X = []  # 特征
    y = []  # 标签
    
    # 加载每个类别的数据
    for label, class_name in enumerate(['W', 'N1', 'N2']):
        class_dir = data_path / class_name
        
        if not class_dir.exists():
            logger.warning(f"目录不存在: {class_dir}")
            continue
        
        # 读取所有 .npy 文件
        samples = list(class_dir.glob('*.npy'))
        logger.info(f"类别 {class_name}: 找到 {len(samples)} 个样本")
        
        for sample_file in samples:
            try:
                features = np.load(sample_file)
                X.append(features)
                y.append(label)
            except Exception as e:
                logger.warning(f"无法加载 {sample_file}: {e}")
    
    return np.array(X), np.array(y)


def extract_features_from_edf(edf_file: str, annotations_file: str = None):
    """
    从 EDF 文件提取特征
    
    如果你的数据是 EDF 格式（常见于睡眠数据集），使用这个函数
    """
    try:
        import mne
        from scipy.signal import welch
        
        # 读取 EDF 文件
        raw = mne.io.read_raw_edf(edf_file, preload=True, verbose=False)
        
        # 读取标注（睡眠分期）
        if annotations_file:
            annotations = mne.read_annotations(annotations_file)
            raw.set_annotations(annotations)
        
        # 选择脑电通道
        eeg_channels = [ch for ch in raw.ch_names if 'EEG' in ch.upper()]
        if not eeg_channels:
            eeg_channels = raw.ch_names[:6]  # 使用前6个通道
        
        raw.pick_channels(eeg_channels)
        
        # 滤波 (0.5-35 Hz)
        raw.filter(0.5, 35, fir_design='firwin')
        
        # 提取30秒 epochs
        epochs = mne.make_fixed_length_epochs(raw, duration=30.0, preload=True)
        
        # 提取特征
        features_list = []
        labels_list = []
        
        for epoch in epochs:
            # 计算功率谱密度
            freqs_list = []
            psd_list = []
            
            for ch_idx in range(epoch.shape[0]):
                freqs, psd = welch(epoch[ch_idx], fs=raw.info['sfreq'], 
                                  nperseg=256)
                freqs_list.append(freqs)
                psd_list.append(psd)
            
            # 提取频段能量
            # Delta (0.5-4 Hz), Theta (4-8 Hz), Alpha (8-13 Hz), Beta (13-30 Hz)
            bands = {
                'delta': (0.5, 4),
                'theta': (4, 8),
                'alpha': (8, 13),
                'beta': (13, 30)
            }
            
            features = []
            for psd, freqs in zip(psd_list, freqs_list):
                for band_name, (low, high) in bands.items():
                    mask = (freqs >= low) & (freqs <= high)
                    band_power = np.mean(psd[mask])
                    features.append(band_power)
            
            features_list.append(features)
        
        return np.array(features_list)
        
    except ImportError:
        logger.error("需要安装 mne 库: pip install mne")
        return None
    except Exception as e:
        logger.error(f"提取特征失败: {e}")
        return None


def train_classifier(X_train, y_train, X_test, y_test):
    """
    训练随机森林分类器
    """
    logger.info("开始训练分类器...")
    logger.info(f"训练集大小: {X_train.shape}")
    logger.info(f"测试集大小: {X_test.shape}")
    
    # 创建分类器
    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=15,
        min_samples_split=10,
        min_samples_leaf=4,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1
    )
    
    # 训练
    clf.fit(X_train, y_train)
    
    # 交叉验证
    cv_scores = cross_val_score(clf, X_train, y_train, cv=5)
    logger.info(f"交叉验证准确率: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
    
    # 测试集评估
    y_pred = clf.predict(X_test)
    test_acc = (y_pred == y_test).mean()
    
    logger.info(f"\n测试集准确率: {test_acc:.3f}")
    logger.info(f"\n分类报告:")
    logger.info(classification_report(y_test, y_pred, 
                                     target_names=['W (清醒)', 'N1 (浅睡)', 'N2 (深睡)']))
    
    logger.info(f"\n混淆矩阵:")
    logger.info(confusion_matrix(y_test, y_pred))
    
    return clf


def save_model(clf, output_path: str):
    """保存模型"""
    with open(output_path, 'wb') as f:
        pickle.dump(clf, f)
    logger.info(f"✓ 模型已保存到: {output_path}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("""
使用方法:

1. 如果你有已经提取好特征的数据（.npy 格式）:
   python train_sleep_classifier.py /path/to/data_dir

   数据目录结构:
   data_dir/
     W/
       sample_001.npy
       sample_002.npy
       ...
     N1/
       sample_001.npy
       ...
     N2/
       sample_001.npy
       ...

2. 如果你有 EDF 格式的原始数据，请修改脚本使用 extract_features_from_edf 函数

训练完成后，模型会保存到 ./sleep_classifier_W_N1_N2.pkl
        """)
        sys.exit(1)
    
    data_dir = sys.argv[1]
    
    # 加载数据
    logger.info(f"从 {data_dir} 加载数据...")
    X, y = load_sleep_data(data_dir)
    
    if len(X) == 0:
        logger.error("没有加载到任何数据！请检查数据目录。")
        sys.exit(1)
    
    logger.info(f"总共加载 {len(X)} 个样本")
    logger.info(f"类别分布: W={np.sum(y==0)}, N1={np.sum(y==1)}, N2={np.sum(y==2)}")
    
    # 划分训练集和测试集
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    # 训练
    clf = train_classifier(X_train, y_train, X_test, y_test)
    
    # 保存模型
    output_path = "./sleep_classifier_W_N1_N2.pkl"
    save_model(clf, output_path)
    
    logger.info("\n训练完成！")
