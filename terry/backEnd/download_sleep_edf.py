"""
下载 Sleep-EDF 数据集并训练模型
"""
import os
import urllib.request
import mne
import numpy as np
from pathlib import Path
import pickle
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from scipy.signal import welch

DATA_DIR = Path("./sleep_edf_data")
DATA_DIR.mkdir(exist_ok=True)

# Sleep-EDF 数据集 URL (从 PhysioNet)
SLEEP_EDF_BASE = "https://physionet.org/files/sleep-edfx/1.0.0/"

# 示例文件（你可以添加更多）
FILES = [
    "sleep-cassette/SC4001E0-PSG.edf",
    "sleep-cassette/SC4001EC-Hypnogram.edf",
    "sleep-cassette/SC4002E0-PSG.edf",
    "sleep-cassette/SC4002EC-Hypnogram.edf",
]

def download_file(url, output_path):
    """下载文件"""
    if output_path.exists():
        print(f"✓ 已存在: {output_path.name}")
        return
    
    print(f"下载: {url}")
    try:
        urllib.request.urlretrieve(url, output_path)
        print(f"✓ 完成: {output_path.name}")
    except Exception as e:
        print(f"✗ 失败: {e}")

def extract_features(raw, annotations):
    """提取睡眠特征"""
    # 选择 EEG 通道
    eeg_chs = [ch for ch in raw.ch_names if 'EEG' in ch.upper()][:2]
    if not eeg_chs:
        eeg_chs = ['Fpz-Cz', 'Pz-Oz']  # Sleep-EDF 标准通道
    
    raw.pick_channels(eeg_chs, ordered=True)
    raw.filter(0.5, 35)
    
    # 创建30秒 epochs
    events, event_id = mne.events_from_annotations(raw, event_id='auto')
    
    # 映射睡眠分期
    # Sleep-EDF: 0=W, 1=N1, 2=N2, 3=N3, 4=REM
    # 我们只要 W, N1, N2
    stage_map = {
        'Sleep stage W': 0,
        'Sleep stage 1': 1,
        'Sleep stage 2': 2,
        'Sleep stage 3': 3,
        'Sleep stage 4': 3,  # N3
        'Sleep stage R': 4,  # REM
    }
    
    epochs = mne.Epochs(raw, events, event_id=event_id,
                       tmin=0, tmax=30, baseline=None, preload=True)
    
    X_list = []
    y_list = []
    
    for epoch, event_type in zip(epochs, epochs.events[:, 2]):
        # 获取标签
        stage_name = [k for k, v in event_id.items() if v == event_type]
        if not stage_name:
            continue
        
        stage_name = stage_name[0]
        if stage_name not in stage_map:
            continue
        
        label = stage_map[stage_name]
        
        # 只保留 W / N1 / N2
        if label > 2:
            continue
        
        # 提取特征
        features = []
        for ch_data in epoch:
            freqs, psd = welch(ch_data, fs=100, nperseg=256)
            
            # Delta, Theta, Alpha, Beta
            bands = [(0.5, 4), (4, 8), (8, 13), (13, 30)]
            for low, high in bands:
                mask = (freqs >= low) & (freqs <= high)
                features.append(np.log(np.mean(psd[mask]) + 1e-10))
        
        X_list.append(features)
        y_list.append(label)
    
    return np.array(X_list), np.array(y_list)

def main():
    print("=" * 60)
    print("Sleep-EDF 数据集下载与训练")
    print("=" * 60)
    
    # 下载数据
    print("\n步骤 1: 下载数据...")
    for file_path in FILES:
        url = SLEEP_EDF_BASE + file_path
        output = DATA_DIR / Path(file_path).name
        download_file(url, output)
    
    print("\n步骤 2: 提取特征...")
    X_all = []
    y_all = []
    
    psg_files = sorted(DATA_DIR.glob("*-PSG.edf"))
    
    for psg_file in psg_files:
        hyp_file = psg_file.parent / psg_file.name.replace("-PSG.edf", "EC-Hypnogram.edf")
        
        if not hyp_file.exists():
            print(f"✗ 缺少标注文件: {hyp_file.name}")
            continue
        
        print(f"处理: {psg_file.name}")
        
        try:
            raw = mne.io.read_raw_edf(psg_file, preload=True, verbose=False)
            annot = mne.read_annotations(hyp_file)
            raw.set_annotations(annot)
            
            X, y = extract_features(raw, annot)
            X_all.append(X)
            y_all.append(y)
            
            print(f"  ✓ 提取 {len(X)} 个样本")
            
        except Exception as e:
            print(f"  ✗ 错误: {e}")
    
    if not X_all:
        print("\n❌ 没有提取到任何数据！")
        return
    
    X_all = np.vstack(X_all)
    y_all = np.hstack(y_all)
    
    print(f"\n总样本数: {len(X_all)}")
    print(f"  W  (清醒): {np.sum(y_all == 0)}")
    print(f"  N1 (浅睡): {np.sum(y_all == 1)}")
    print(f"  N2 (深睡): {np.sum(y_all == 2)}")
    
    # 训练
    print("\n步骤 3: 训练模型...")
    X_train, X_test, y_train, y_test = train_test_split(
        X_all, y_all, test_size=0.2, random_state=42, stratify=y_all
    )
    
    clf = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)
    clf.fit(X_train, y_train)
    
    # 评估
    y_pred = clf.predict(X_test)
    acc = (y_pred == y_test).mean()
    
    print(f"\n测试准确率: {acc:.1%}")
    print("\n分类报告:")
    print(classification_report(y_test, y_pred,
                               target_names=['W', 'N1', 'N2']))
    
    # 保存
    model_path = "./sleep_classifier_W_N1_N2.pkl"
    with open(model_path, 'wb') as f:
        pickle.dump(clf, f)
    
    print(f"\n✓ 模型已保存: {model_path}")

if __name__ == "__main__":
    try:
        import mne
        main()
    except ImportError:
        print("需要安装 mne 库:")
        print("pip install mne")
