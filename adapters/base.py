"""広告プラットフォーム アダプター基底クラス"""

from abc import ABC, abstractmethod


class AdsAdapter(ABC):
    """全アダプターが実装すべきインターフェース"""

    @abstractmethod
    def fetch_campaigns(self, date_from: str, date_to: str) -> list[dict]:
        """キャンペーン一覧＋KPIを返す

        Returns:
            list[dict]: 各要素は以下のキーを持つ
                - campaign_id: str
                - campaign_name: str
                - spend: float
                - impressions: int
                - clicks: int
                - conversions: int
                - revenue: float
                - ctr: float
                - cpc: float
                - cpm: float
                - cpa: float
                - roas: float
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_daily_metrics(self, date_from: str, date_to: str) -> list[dict]:
        """日別の集計データを返す

        Returns:
            list[dict]: 各要素は以下のキーを持つ
                - date: str (YYYY-MM-DD)
                - spend: float
                - impressions: int
                - clicks: int
                - conversions: int
                - revenue: float
                - cpa: float
                - roas: float
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_adsets(self, campaign_id: str, date_from: str, date_to: str) -> list[dict]:
        """広告セット一覧＋KPIを返す

        Returns:
            list[dict]: 各要素は以下のキーを持つ
                - adset_id: str
                - adset_name: str
                - spend: float
                - impressions: int
                - clicks: int
                - conversions: int
                - revenue: float
                - ctr: float
                - cpc: float
                - cpa: float
                - roas: float
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_ads(self, adset_id: str, date_from: str, date_to: str) -> list[dict]:
        """広告一覧＋KPIを返す

        Returns:
            list[dict]: 各要素は以下のキーを持つ
                - ad_id: str
                - ad_name: str
                - spend: float
                - impressions: int
                - clicks: int
                - conversions: int
                - revenue: float
                - ctr: float
                - cpc: float
                - cpa: float
                - roas: float
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_all_adsets(self, date_from: str, date_to: str) -> list[dict]:
        """全広告セット一覧＋KPIを返す（キャンペーン指定なし）"""
        raise NotImplementedError

    @abstractmethod
    def fetch_all_ads(self, date_from: str, date_to: str) -> list[dict]:
        """全広告一覧＋KPIを返す（広告セット指定なし）"""
        raise NotImplementedError

    @abstractmethod
    def fetch_age_gender_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        """年齢×性別の内訳を返す"""
        raise NotImplementedError

    @abstractmethod
    def fetch_region_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        """地域別の内訳を返す"""
        raise NotImplementedError

    @abstractmethod
    def fetch_frequency(self, date_from: str, date_to: str) -> dict:
        """フリークエンシー情報を返す"""
        raise NotImplementedError

    @abstractmethod
    def fetch_adset_targeting(self, adset_id: str) -> dict:
        """広告セットのターゲティング情報を返す

        Returns:
            dict:
                - age: str (例: "18〜65歳")
                - genders: str (例: "男性、女性")
                - locations: str (例: "日本")
                - interests: str (例: "健康、美容")
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_ad_creative(self, ad_id: str) -> dict:
        """広告のクリエイティブ情報を返す

        Returns:
            dict:
                - title: str
                - body: str
                - image_url: str
                - thumbnail_url: str
        """
        raise NotImplementedError

    @abstractmethod
    def platform_name(self) -> str:
        """プラットフォーム名を返す（例: 'Meta広告'）"""
        raise NotImplementedError
