<?php
declare(strict_types=1);

// Copy outside public/. Generate secrets with bin/setup.php; never commit them.
return [
    'base_url' => 'http://127.0.0.1:8080',
    'environment' => 'production', // local permits HTTP on loopback only.
    'storage_path' => __DIR__ . '/var',
    'public_path' => __DIR__ . '/public',
    'secret' => '',
    'admin_password_hash' => '',
    'allow_bookings' => false,
    'venue_public_enabled' => false,
    'venue_address' => '2735 Harrison Ave NW, Canton, OH 44709',
    'arrival_text' => 'Arrival and parking instructions are awaiting host verification. Do not use this site as an invitation to walk in.',
    'twitch_channel' => 'cantonrefinery',
    'twitch_parents' => [], // Exact hostname(s), no scheme or path.
    'mail_transport' => 'disabled', // disabled, local (PHP mail), or smtp.
    'email_from' => '',
    'smtp_host' => '',
    'smtp_port' => 587,
    'smtp_username' => '',
    'smtp_password' => '',
    'vod_retention_days' => 7,
    'retention_days' => 90,
    'meta_pixel_id' => '', // Reserved; no Meta integration is shipped in this MVP.
];
