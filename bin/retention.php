<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
if (PHP_SAPI!=='cli') exit(1);
$days=(int)config()['retention_days'];
if ($days<1) throw new RuntimeException('Retention must be at least one day.');
$cutoff=utc((new DateTimeImmutable())->modify('-'.$days.' days'));
transaction(function () use ($cutoff): void {
    query("DELETE FROM bookings WHERE created_at<? AND status IN ('cancelled','performed','no_show')",[$cutoff]);
    query('DELETE FROM writer_submissions WHERE created_at<?',[$cutoff]);
    query('DELETE FROM booking_tokens WHERE expires_at<?',[utc()]);
    query('DELETE FROM rate_limits WHERE window_start<?',[time()-86400]);
    query('DELETE FROM host_actions WHERE created_at<?',[$cutoff]);
    query('DELETE FROM sanitation_checks WHERE created_at<?',[$cutoff]);
});
echo "Retention applied. Backup expiration is a separate operator task.\n";
