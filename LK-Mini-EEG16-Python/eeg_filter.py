from typing import Dict, List, Optional
from iir_filter import IirFilter

class EegFilter:
    """
    脑电信号(EEG)滤波器
    提供针对不同采样率的脑电信号滤波处理
    """

    def __init__(self):
        """初始化脑电信号滤波器，自动配置 125、250、500、1000、2000 Hz 采样率的滤波器"""
        self._filters_by_sampling_rate: Dict[int, List[IirFilter]] = {}

        self._initialize_filters_for_125hz()
        self._initialize_filters_for_250hz()
        self._initialize_filters_for_500hz()
        self._initialize_filters_for_1000hz()
        self._initialize_filters_for_2000hz()

    # ----------------------------------------------------------------------
    # 初始化各采样率的滤波器组
    # ----------------------------------------------------------------------
    def _initialize_filters_for_125hz(self):
        """初始化 125Hz 采样率的滤波器组"""
        filters = []

        # 5Hz 高通滤波器（4阶巴特沃斯）
        high_pass_num = [0.719359552810643, -2.87743821124257, 4.31615731686386,
                         -2.87743821124257, 0.719359552810643]
        high_pass_den = [1, -3.34406783771187, 4.23886395088406,
                         -2.40934285658632, 0.517478199788040]
        filters.append(IirFilter(high_pass_num, high_pass_den))

        # 50Hz 工频陷波器（单极点）
        notch_num = [0.917047349314333, 1.48381378048359, 0.917047349314333]
        notch_den = [1, 1.48381378048359, 0.834094698628666]
        filters.append(IirFilter(notch_num, notch_den))

        self._filters_by_sampling_rate[125] = filters

    def _initialize_filters_for_250hz(self):
        """初始化 250Hz 采样率的滤波器组"""
        filters = []

        # 5Hz 高通滤波器（4阶巴特沃斯）
        high_pass_num = [0.848475295524359, -3.39390118209744, 5.09085177314616,
                         -3.39390118209744, 0.848475295524359]
        high_pass_den = [1, -3.67172908916194, 5.06799838673419,
                         -3.11596692520175, 0.719910327291872]
        filters.append(IirFilter(high_pass_num, high_pass_den))

        # 50Hz低通滤波器（6阶巴特沃斯）
        low_pass_num = [0.010312874762664404, 0.06187724857598642, 0.15469312143996605,
                        0.20625749525328807, 0.15469312143996605, 0.06187724857598642,
                        0.010312874762664404]
        low_pass_den = [1, -1.1876006801756145, 1.3052133492885498, -0.6743275252979981,
                        0.2634693482801379, -0.05175303387964128, 0.00502252659508814]
        filters.append(IirFilter(low_pass_num, low_pass_den))

        # 50Hz工频陷波器（单极点）
        notch_num = [0.936813880017972, -0.578982818983773, 0.936813880017972]
        notch_den = [1, -0.578982818983773, 0.873627760035944]
        filters.append(IirFilter(notch_num, notch_den))

        self._filters_by_sampling_rate[250] = filters

    def _initialize_filters_for_500hz(self):
        """初始化 500Hz 采样率的滤波器组"""
        filters = []

        # 5Hz 高通滤波器（4阶巴特沃斯）
        high_pass_num = [0.921170993499942, -3.68468397399977, 5.52702596099965,
                         -3.68468397399977, 0.921170993499942]
        high_pass_den = [1, -3.83582554064735, 5.52081913662223,
                         -3.53353521946301, 0.848555999266477]
        filters.append(IirFilter(high_pass_num, high_pass_den))

        # 50 Hz 低通滤波器（6阶巴特沃斯）
        low_pass_num = [0.0003405376527201276, 0.0020432259163207654, 0.005108064790801914,
                        0.006810753054402552, 0.005108064790801914, 0.0020432259163207654,
                        0.0003405376527201276]
        low_pass_den = [1, -3.5794347983311923, 5.658667165933625, -4.96541522877857,
                        2.529494905841447, -0.7052741145099005, 0.08375647961867892]
        filters.append(IirFilter(low_pass_num, low_pass_den))

        # 50Hz工频陷波器（单极点）
        notch_num = [0.967437388703836, -1.56534657691025, 0.967437388703836]
        notch_den = [1, -1.56534657691025, 0.934874777407671]
        filters.append(IirFilter(notch_num, notch_den))

        self._filters_by_sampling_rate[500] = filters

    def _initialize_filters_for_1000hz(self):
        """初始化 1000Hz 采样率的滤波器组"""
        filters = []

        # 5Hz 高通滤波器（4阶巴特沃斯）
        high_pass_num = [0.959782230087239, -3.83912892034895, 5.75869338052343,
                         -3.83912892034895, 0.959782230087239]
        high_pass_den = [1, -3.91790786539199, 5.75707637911807,
                         -3.76034950769453, 0.921181929191236]
        filters.append(IirFilter(high_pass_num, high_pass_den))

        # 50 Hz 低通滤波器（6阶巴特沃斯）
        low_pass_num = [8.576557073259404e-06, 5.145934243955643e-05, 0.00012864835609889108,
                        0.00017153114146518808, 0.00012864835609889108, 5.145934243955643e-05,
                        8.576557073259404e-06]
        low_pass_den = [1, -4.787135498852133, 9.649517728721909, -10.46907889254386,
                        6.441111881008067, -2.1290387500304497, 0.295172431349155]
        filters.append(IirFilter(low_pass_num, low_pass_den))

        # 50Hz工频陷波器（单极点）
        notch_num = [0.983457100401067, -1.87064656766634, 0.983457100401067]
        notch_den = [1, -1.87064656766634, 0.966914200802133]
        filters.append(IirFilter(notch_num, notch_den))

        self._filters_by_sampling_rate[1000] = filters

    def _initialize_filters_for_2000hz(self):
        """初始化 2000Hz 采样率的滤波器组"""
        filters = []

        # 5Hz 高通滤波器（4阶巴特沃斯）
        high_pass_num = [0.979685487190404, -3.91874194876162, 5.87811292314242,
                         -3.91874194876162, 0.979685487190404]
        high_pass_den = [1, -3.95895331864708, 5.87770027353615,
                         -3.87853054905174, 0.959783653811499]
        filters.append(IirFilter(high_pass_num, high_pass_den))

        # 50Hz 低通滤波器（6阶巴特沃斯）
        low_pass_num = [1.7536549719840575e-07, 1.0521929831904345e-06, 2.6304824579760863e-06,
                        3.507309943968115e-06, 2.6304824579760863e-06, 1.0521929831904345e-06,
                        1.7536549719840575e-07]
        low_pass_den = [1, -5.393212484861354, 12.147425170416897, -14.623787566607604,
                        9.923048570770401, -3.5980635338866374, 0.5446010675601195]
        filters.append(IirFilter(low_pass_num, low_pass_den))

        # 50Hz工频陷波器（单极点）
        notch_num = [0.991660562744315, -1.95890315130115, 0.991660562744315]
        notch_den = [1, -1.95890315130115, 0.983321125488630]
        filters.append(IirFilter(notch_num, notch_den))

        self._filters_by_sampling_rate[2000] = filters

    # ----------------------------------------------------------------------
    # 公共接口
    # ----------------------------------------------------------------------
    def process_sample(self, sampling_rate: int, input_sample: float) -> float:
        """
        处理单个脑电信号样本

        参数:
            sampling_rate: 采样率 (Hz)
            input_sample: 输入样本值

        返回:
            滤波后的样本值
        """
        output = input_sample
        filters = self._filters_by_sampling_rate.get(sampling_rate)
        if filters:
            for f in filters:
                output = f.process_sample(output)
        return output

    def process_samples(self, sampling_rate: int, input_samples: List[float]) -> List[float]:
        """
        批量处理脑电信号样本

        参数:
            sampling_rate: 采样率 (Hz)
            input_samples: 输入样本列表

        返回:
            滤波后的样本列表
        """
        if input_samples is None:
            raise ValueError("input_samples cannot be None")
        return [self.process_sample(sampling_rate, x) for x in input_samples]

    def reset_filters(self, sampling_rate: int) -> None:
        """
        重置指定采样率的所有滤波器状态

        参数:
            sampling_rate: 采样率 (Hz)
        """
        filters = self._filters_by_sampling_rate.get(sampling_rate)
        if filters:
            for f in filters:
                f.reset()

    def reset_all_filters(self) -> None:
        """重置所有采样率的所有滤波器状态"""
        for filters in self._filters_by_sampling_rate.values():
            for f in filters:
                f.reset()

    def supports_sampling_rate(self, sampling_rate: int) -> bool:
        """检查是否支持指定的采样率"""
        return sampling_rate in self._filters_by_sampling_rate

    def get_supported_sampling_rates(self) -> List[int]:
        """获取支持的采样率列表"""
        return list(self._filters_by_sampling_rate.keys())

    # ----------------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------------
    @staticmethod
    def _generate_comb_filter_coefficients(start_value: float, end_value: float,
                                           filter_order: int) -> List[float]:
        """
        生成梳状滤波器系数：长度为 filter_order+1，第一个元素为 start_value，
        最后一个元素为 end_value，中间填充零。

        参数:
            start_value: 起始系数值
            end_value: 结束系数值
            filter_order: 滤波器阶数（决定了零的个数）

        返回:
            系数列表
        """
        coeffs = [start_value] + [0.0] * (filter_order - 1) + [end_value]
        return coeffs