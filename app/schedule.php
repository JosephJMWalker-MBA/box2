<?php
declare(strict_types=1);

function show_date(string $date): DateTimeImmutable
{
    $parsed = DateTimeImmutable::createFromFormat('!Y-m-d', $date, new DateTimeZone(BOX2_ZONE));
    if (!$parsed || $parsed->format('Y-m-d') !== $date) throw new InvalidArgumentException('Invalid show date.');
    return $parsed;
}

function local_instant(string $date, string $time): DateTimeImmutable
{
    if (!preg_match('/^\d{2}:\d{2}$/D', $time)) throw new InvalidArgumentException('Use HH:MM for hours.');
    $text = $date . ' ' . $time;
    $zone = new DateTimeZone(BOX2_ZONE);
    $instant = DateTimeImmutable::createFromFormat('!Y-m-d H:i', $text, $zone);
    if (!$instant || $instant->format('Y-m-d H:i') !== $text) {
        throw new InvalidArgumentException('These hours include a nonexistent local time. Choose explicit valid hours.');
    }
    // Reject ambiguous endpoints; slots themselves are generated as UTC instants through a repeated hour.
    $wall = strtotime($text . ' UTC');
    $matches = [];
    foreach ($zone->getTransitions($wall - 86400, $wall + 86400) as $transition) {
        $candidate = (new DateTimeImmutable('@' . ($wall - $transition['offset'])))->setTimezone($zone);
        if ($candidate->format('Y-m-d H:i') === $text) $matches[$candidate->getTimestamp()] = true;
    }
    if (count($matches) !== 1) throw new InvalidArgumentException('Ambiguous local hours: choose an unambiguous endpoint.');
    return $instant;
}

function schedule_night(string $date, string $start = '21:00', string $end = '02:00'): int
{
    $day = show_date($date);
    $endDate = $end <= $start ? $day->modify('+1 day')->format('Y-m-d') : $date;
    $from = local_instant($date, $start);
    $until = local_instant($endDate, $end);
    $seconds = $until->getTimestamp() - $from->getTimestamp();
    if ($seconds <= 0 || $seconds > 28800 || $seconds % 600 !== 0) {
        throw new InvalidArgumentException('Hours must span at most eight hours in ten-minute blocks.');
    }
    return transaction(function () use ($date, $from, $until): int {
        $existing = query('SELECT id FROM show_nights WHERE show_date=?', [$date])->fetchColumn();
        if ($existing) return (int) $existing;
        query('INSERT INTO show_nights(show_date,timezone,start_at_utc,end_at_utc,created_at) VALUES (?,?,?,?,?)',
            [$date, BOX2_ZONE, utc($from), utc($until), utc()]);
        $id = (int) db()->lastInsertId();
        for ($stamp = $from->getTimestamp(), $i = 0; $stamp < $until->getTimestamp(); $stamp += 600, $i++) {
            // 22 online blocks; six host holds and two separately labelled private rehearsals.
            $visibility = $i < 22 ? 'public' : ($i >= ($until->getTimestamp() - $from->getTimestamp()) / 600 - 2 ? 'private' : 'hold');
            query('INSERT INTO slots(show_night_id,start_at_utc,end_at_utc,visibility) VALUES (?,?,?,?)',
                [$id, utc(new DateTimeImmutable('@' . $stamp)), utc(new DateTimeImmutable('@' . ($stamp + 600))), $visibility]);
        }
        return $id;
    });
}

function generate_schedule(string $firstDate, int $days = 28): array
{
    if ($days < 1 || $days > 90) throw new InvalidArgumentException('Schedule horizon must be 1-90 days.');
    $day = show_date($firstDate);
    $notices = [];
    for ($i = 0; $i < $days; $i++, $day = $day->modify('+1 day')) {
        if ($day->format('N') === '2') continue;
        $date = $day->format('Y-m-d');
        if (query('SELECT id FROM show_nights WHERE show_date=?', [$date])->fetchColumn()) continue;
        try {
            schedule_night($date);
        } catch (InvalidArgumentException $exception) {
            $notices[] = $date . ': ' . $exception->getMessage();
            // Persist a closed night rather than silently normalizing an invalid DST endpoint.
            query("INSERT OR IGNORE INTO show_nights(show_date,timezone,start_at_utc,end_at_utc,status,override_note,created_at)
                VALUES (?,?,?,?,'closed',?,?)", [$date, BOX2_ZONE, utc(local_instant($date, '21:00')),
                utc(local_instant($day->modify('+1 day')->format('Y-m-d'), '03:00')), $exception->getMessage(), utc()]);
        }
    }
    return $notices;
}

function availability(int $night): array
{
    return query("SELECT s.id,s.start_at_utc,s.end_at_utc,s.visibility,
        CASE WHEN n.status='closed' OR s.status='closed' THEN 'closed'
         WHEN s.visibility='hold' THEN 'held'
         WHEN b.id IS NOT NULL THEN 'booked'
         WHEN s.start_at_utc <= ? THEN 'closed' ELSE 'available' END AS state
        FROM slots s JOIN show_nights n ON n.id=s.show_night_id
        LEFT JOIN bookings b ON b.slot_id=s.id AND b.status!='cancelled'
        WHERE n.id=? ORDER BY s.start_at_utc", [utc(), $night])->fetchAll();
}

function local_label(string $instant): string
{
    return (new DateTimeImmutable($instant))->setTimezone(new DateTimeZone(BOX2_ZONE))->format('D M j, g:i A T');
}

function override_night(int $id, array $data): void
{
    require_admin();
    $night = query('SELECT * FROM show_nights WHERE id=?', [$id])->fetch();
    if (!$night) throw new InvalidArgumentException('Show not found.');
    $status = field($data, 'status', 10, true);
    if (!in_array($status, ['open','closed'], true)) throw new InvalidArgumentException('Invalid show status.');
    $note = field($data, 'override_note', 300);
    $guest = field($data, 'guest_host', 100);
    $from = local_instant($night['show_date'], field($data, 'start', 5, true));
    $endTime = field($data, 'end', 5, true);
    $endDate = $endTime <= $from->format('H:i') ? show_date($night['show_date'])->modify('+1 day')->format('Y-m-d') : $night['show_date'];
    $until = local_instant($endDate, $endTime);
    $span = $until->getTimestamp() - $from->getTimestamp();
    if ($span <= 0 || $span > 28800 || $span % 600) throw new InvalidArgumentException('Invalid show hours.');
    transaction(function () use ($id,$status,$note,$guest,$from,$until): void {
        $slots = query('SELECT * FROM slots WHERE show_night_id=? ORDER BY start_at_utc', [$id])->fetchAll();
        $active = (int) query("SELECT count(*) FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.show_night_id=? AND b.status!='cancelled'", [$id])->fetchColumn();
        if ($active && (!$slots || $slots[0]['start_at_utc'] !== utc($from) || end($slots)['end_at_utc'] !== utc($until))) {
            throw new InvalidArgumentException('Cancel affected bookings first; occupied slots cannot be moved.');
        }
        query('UPDATE show_nights SET status=?,override_note=?,guest_host=?,start_at_utc=?,end_at_utc=? WHERE id=?',
            [$status,$note,$guest,utc($from),utc($until),$id]);
        // Never change slot identities; close old out-of-hours slots and insert missing ones.
        query("UPDATE slots SET status='closed' WHERE show_night_id=? AND (start_at_utc < ? OR end_at_utc > ?)", [$id,utc($from),utc($until)]);
        for ($stamp=$from->getTimestamp(); $stamp<$until->getTimestamp(); $stamp+=600) {
            query("INSERT OR IGNORE INTO slots(show_night_id,start_at_utc,end_at_utc,visibility) VALUES (?,?,?,'hold')",
                [$id,utc(new DateTimeImmutable('@'.$stamp)),utc(new DateTimeImmutable('@'.($stamp+600)))]);
        }
        audit('show_override',(string)$id);
    });
}
