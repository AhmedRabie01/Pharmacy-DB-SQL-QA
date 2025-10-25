IMPORTANT_QUERIES = {
    "الإيرادات الشهرية الإجمالية": """
    SELECT
      YEAR([s].[Date]) AS [Year],
      MONTH([s].[Date]) AS [Month],
      SUM([s].[QuantitySold]*[s].[SellingPrice]) AS [TotalRevenue]
    FROM [dbo].[selling] AS [s]
    GROUP BY YEAR([s].[Date]), MONTH([s].[Date])
    ORDER BY [Year],[Month];
    """,
    "صافي الربح لكل منتج (تقريبي)": """
    SELECT
      [p].[ProductCode], [p].[ProductName],
      SUM([s].[QuantitySold]*([s].[SellingPrice]-COALESCE([s].[ManufacturerCost],0))) AS [ApproxProfit],
      SUM([s].[QuantitySold]) AS [TotalQty]
    FROM [dbo].[selling] AS [s]
    JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode]
    GROUP BY [p].[ProductCode],[p].[ProductName]
    ORDER BY [ApproxProfit] DESC;
    """,
    "المنتجات الراكدة (تم الشراء ولم تُبع خلال 90 يوماً)": """
    SELECT DISTINCT [p].[ProductCode],[p].[ProductName]
    FROM [dbo].[buying] AS [b]
    JOIN [dbo].[products] AS [p] ON [b].[ProductCode]=[p].[ProductCode]
    WHERE NOT EXISTS (
      SELECT 1 FROM [dbo].[selling] AS [s]
      WHERE [s].[ProductCode]=[b].[ProductCode]
        AND [s].[Date] >= DATEADD(day,-90,GETDATE())
    )
    ORDER BY [p].[ProductName];
    """,
    "الفجوة بين الشراء والبيع (كمية ومالياً) لكل منتج": """
    SELECT
      [p].[ProductCode],[p].[ProductName],
      SUM(COALESCE([b].[NetQuantity],[b].[QuantityBuying])) AS [QtyBought],
      SUM([s].[QuantitySold]) AS [QtySold],
      SUM(COALESCE([b].[NetCost],[b].[CostBuying])) AS [CostBought],
      SUM([s].[QuantitySold]*[s].[SellingPrice]) AS [RevenueSold]
    FROM [dbo].[products] AS [p]
    LEFT JOIN [dbo].[buying] AS [b] ON [b].[ProductCode]=[p].[ProductCode]
    LEFT JOIN [dbo].[selling] AS [s] ON [s].[ProductCode]=[p].[ProductCode]
    GROUP BY [p].[ProductCode],[p].[ProductName]
    ORDER BY ([RevenueSold]-[CostBought]) DESC;
    """,
    "أفضل 10 منتجات حسب الهامش المتوسط (سعر البيع - تكلفة المصنع)": """
    SELECT TOP 10
      [p].[ProductCode],[p].[ProductName],
      AVG([s].[SellingPrice]-COALESCE([s].[ManufacturerCost],0)) AS [AvgMargin],
      COUNT([s].[SellingID]) AS [Transactions]
    FROM [dbo].[selling] AS [s]
    JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode]
    GROUP BY [p].[ProductCode],[p].[ProductName]
    HAVING COUNT([s].[SellingID]) >= 5
    ORDER BY [AvgMargin] DESC;
    """,
    "تنبيهات مخزون منخفض (Quantity <= 5)": """
    SELECT [ProductCode],[ProductName],[Quantity],[Classification]
    FROM [dbo].[products]
    WHERE [Quantity] <= 5
    ORDER BY [Quantity] ASC, [ProductName];
    """,
    "أداء الفروع/المخازن حسب الإيراد": """
    SELECT [s].[Store],
           SUM([s].[QuantitySold]*[s].[SellingPrice]) AS [Revenue],
           SUM([s].[QuantitySold]) AS [Qty]
    FROM [dbo].[selling] AS [s]
    GROUP BY [s].[Store]
    ORDER BY [Revenue] DESC;
    """,
    "المنتجات ذات النشاط الشهري المستمر (>= 6 أشهر مختلفة)": """
    SELECT
      [p].[ProductCode],[p].[ProductName],
      COUNT(DISTINCT FORMAT([s].[Date],'yyyy-MM')) AS [MonthsWithSales]
    FROM [dbo].[selling] AS [s]
    JOIN [dbo].[products] AS [p] ON [s].[ProductCode]=[p].[ProductCode]
    GROUP BY [p].[ProductCode],[p].[ProductName]
    HAVING COUNT(DISTINCT FORMAT([s].[Date],'yyyy-MM')) >= 6
    ORDER BY [MonthsWithSales] DESC;
    """
}
