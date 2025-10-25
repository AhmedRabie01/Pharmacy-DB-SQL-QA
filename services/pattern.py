import re

class PatternSQLGenerator:
    """
    High-precision patterns for common pharmacy analytics (Arabic/English).
    """
    @staticmethod
    def generate(question: str) -> str | None:
        q = (question or "").lower()

        def has_any(words): return any(w in q for w in words)

        if has_any(["all products", "جميع المنتجات", "show products", "كل المنتجات"]):
            return (
                "SELECT [ProductCode],[ProductName],[Quantity],[Classification] "
                "FROM [dbo].[products] ORDER BY [ProductName];"
            )

        if has_any(["best selling", "أكثر مبيع", "top selling", "most sold", "الأكثر مبيعاً"]):
            return (
                "SELECT TOP 10 [p].[ProductCode],[p].[ProductName], "
                "SUM([s].[QuantitySold]) AS [TotalSold] "
                "FROM [dbo].[selling] AS [s] "
                "JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode] "
                "GROUP BY [p].[ProductCode],[p].[ProductName] "
                "ORDER BY SUM([s].[QuantitySold]) DESC;"
            )

        if has_any(["per month", "شهريا", "في الشهر", "monthly"]):
            nums = re.findall(r"\d+", q)
            threshold = nums[0] if nums else "5"
            return (
                "SELECT [p].[ProductCode],[p].[ProductName], "
                "AVG([s].[QuantitySold]) AS [AvgMonthlySales], "
                "COUNT(DISTINCT FORMAT([s].[Date],'yyyy-MM')) AS [MonthsActive] "
                "FROM [dbo].[selling] AS [s] "
                "JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode] "
                f"GROUP BY [p].[ProductCode],[p].[ProductName] "
                f"HAVING AVG([s].[QuantitySold]) > {threshold} "
                "ORDER BY [AvgMonthlySales] DESC;"
            )

        if has_any(["distinct months", "different months", "شهر مختلف"]):
            nums = re.findall(r"\d+", q)
            threshold = nums[0] if nums else "5"
            return (
                "SELECT [p].[ProductCode],[p].[ProductName], "
                "COUNT(DISTINCT FORMAT([s].[Date],'yyyy-MM')) AS [MonthsWithSales] "
                "FROM [dbo].[selling] AS [s] "
                "JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode] "
                f"GROUP BY [p].[ProductCode],[p].[ProductName] "
                f"HAVING COUNT(DISTINCT FORMAT([s].[Date],'yyyy-MM')) >= {threshold} "
                "ORDER BY [MonthsWithSales] DESC;"
            )

        if has_any(["purchased but never sold", "تم شراؤها ولكن لم تباع", "bought not sold"]):
            return (
                "SELECT DISTINCT [p].[ProductCode],[p].[ProductName],[p].[Classification] "
                "FROM [dbo].[buying] AS [b] "
                "JOIN [dbo].[products] AS [p] ON [b].[ProductCode]=[p].[ProductCode] "
                "WHERE [b].[ProductCode] NOT IN (SELECT DISTINCT [ProductCode] FROM [dbo].[selling]) "
                "ORDER BY [p].[ProductName];"
            )

        if has_any(["revenue", "إجمالي الإيرادات", "total sales", "إجمالي المبيعات"]):
            return (
                "SELECT [p].[ProductCode],[p].[ProductName], "
                "SUM([s].[QuantitySold]) AS [TotalQuantity], "
                "SUM([s].[QuantitySold]*[s].[SellingPrice]) AS [TotalRevenue] "
                "FROM [dbo].[selling] AS [s] "
                "JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode] "
                "GROUP BY [p].[ProductCode],[p].[ProductName] "
                "ORDER BY [TotalRevenue] DESC;"
            )

        return None
