SELECT User_ID, SUM(paid_revenue_rub) paid_revenue
FROM mart_customer_revenue_health
WHERE latest_subscription_status='active'
GROUP BY 1
ORDER BY 2 DESC
