<?php
declare(strict_types=1);

const BOX2_VERSION = '0.1.0';
const BOX2_TERMS = '2026-10-08';
const BOX2_ZONE = 'America/New_York';

function config(?array $override = null): array
{
    static $config;
    if ($override !== null) {
        return $config = $override + require dirname(__DIR__) . '/config.example.php';
    }
    if ($config === null) {
        $config = require dirname(__DIR__) . '/config.example.php';
        $path = getenv('BOX2_CONFIG') ?: dirname(__DIR__) . '/config.local.php';
        if (is_file($path)) {
            $config = (require $path) + $config;
        }
        $url = parse_url($config['base_url']);
        if (!isset($url['host']) || !in_array($url['scheme'] ?? '', ['http', 'https'], true)
            || isset($url['user']) || isset($url['query']) || isset($url['fragment'])) {
            throw new RuntimeException('Invalid base URL configuration.');
        }
    }
    return $config;
}

function utc(?DateTimeImmutable $date = null): string
{
    return ($date ?? new DateTimeImmutable())->setTimezone(new DateTimeZone('UTC'))->format('Y-m-d\TH:i:s\Z');
}

function url(string $path = '/'): string
{
    return rtrim(config()['base_url'], '/') . $path;
}

function e(mixed $value): string
{
    return htmlspecialchars((string) $value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function field(array $data, string $key, int $max, bool $required = false): string
{
    if (isset($data[$key]) && !is_string($data[$key])) {
        throw new InvalidArgumentException('Invalid ' . str_replace('_', ' ', $key) . '.');
    }
    $value = trim($data[$key] ?? '');
    if (($required && $value === '') || mb_strlen($value) > $max || str_contains($value, "\0")) {
        throw new InvalidArgumentException('Check ' . str_replace('_', ' ', $key) . ' (maximum ' . $max . ' characters).');
    }
    return $value;
}

function flag(array $data, string $key): int
{
    return isset($data[$key]) && in_array($data[$key], ['1', 1, true], true) ? 1 : 0;
}

function email_field(array $data, string $key, bool $required = true): string
{
    $email = field($data, $key, 254, $required);
    if ($email !== '' && !filter_var($email, FILTER_VALIDATE_EMAIL)) {
        throw new InvalidArgumentException('Enter a valid email address.');
    }
    return strtolower($email);
}

function secure_request(): bool
{
    // Forwarded headers are intentionally not trusted. Configure HTTPS at the PHP host.
    return ($_SERVER['HTTPS'] ?? '') === 'on' || ($_SERVER['HTTPS'] ?? '') === '1';
}

function local_request(): bool
{
    return config()['environment'] === 'local'
        && in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true);
}

function start_session(): void
{
    if (session_status() === PHP_SESSION_ACTIVE) return;
    ini_set('session.use_strict_mode', '1');
    ini_set('session.use_only_cookies', '1');
    session_name('box2');
    session_set_cookie_params(['secure' => !local_request(), 'httponly' => true,
        'samesite' => 'Lax', 'path' => parse_url(config()['base_url'], PHP_URL_PATH) ?: '/']);
    session_start();
}

function csrf(): string
{
    return $_SESSION['csrf'] ??= bin2hex(random_bytes(32));
}

function verify_csrf(array $data): void
{
    if (!is_string($data['csrf'] ?? null) || !hash_equals(csrf(), $data['csrf'])) {
        throw new InvalidArgumentException('This form expired. Reload the page and try again.');
    }
}

function admin(): bool
{
    if (empty($_SESSION['admin']) || ($_SESSION['last_active'] ?? 0) < time() - 1800) {
        unset($_SESSION['admin']);
        return false;
    }
    $_SESSION['last_active'] = time();
    return true;
}

function require_admin(): void
{
    if (!admin()) throw new RuntimeException('Host authentication required.', 403);
}

function audit(string $action, string $reference = ''): void
{
    query('INSERT INTO host_actions(action,reference,created_at) VALUES (?,?,?)', [$action, $reference, utc()]);
}

function throttle(string $purpose, int $limit, int $seconds = 600): void
{
    $bucket = hash_hmac('sha256', $purpose . ':' . ($_SERVER['REMOTE_ADDR'] ?? 'cli'), config()['secret']);
    $now = time();
    query('INSERT INTO rate_limits(bucket,window_start,hits) VALUES (?,?,1)
        ON CONFLICT(bucket) DO UPDATE SET hits=CASE WHEN window_start <= ? THEN 1 ELSE hits+1 END,
        window_start=CASE WHEN window_start <= ? THEN excluded.window_start ELSE window_start END',
        [$bucket, $now, $now - $seconds, $now - $seconds]);
    if ((int) query('SELECT hits FROM rate_limits WHERE bucket=?', [$bucket])->fetchColumn() > $limit) {
        throw new RuntimeException('Too many attempts. Please try again later.', 429);
    }
}

function forms_ready(): bool
{
    return strlen(config()['secret']) >= 32 && (secure_request() || local_request());
}

function bookings_open(): bool
{
    return config()['allow_bookings'] && config()['venue_public_enabled'] && forms_ready();
}

require_once __DIR__ . '/db.php';
require_once __DIR__ . '/schedule.php';
require_once __DIR__ . '/booking.php';
require_once __DIR__ . '/reminders.php';
require_once __DIR__ . '/media.php';
