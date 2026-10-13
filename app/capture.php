<?php
declare(strict_types=1);

const ROOM_OFF_CHECKS = [
    'room_video_off' => 'OBS/Reolink room video and virtual cameras are disconnected.',
    'room_audio_off' => 'Room microphone/ambient capture routes to OBS and recorders are disconnected; in-room amplification is separate.',
    'desktop_capture_off' => 'macOS/desktop audio, screen capture and private notifications are excluded.',
    'independent_recorders_off' => 'Independent Reolink SD/NVR/cloud and all other room recorders are OFF.',
    'event_capture_off' => 'Camera event snapshots, motion recording and mobile alerts cannot retain the guest.',
    'buffers_reviewed' => 'Outgoing Twitch buffers/delay, VOD, local recording and replay cannot retain room media.',
    'reconnect_disabled' => 'Automatic reconnection cannot restore room sources after a fault or restart.',
];
const HOUSE_CHECKS = [
    'house_isolated' => 'Only an independent prerecorded house source can reach the channel.',
    'house_rights' => 'The house media is rights-cleared and does not imply performer endorsement.',
    'viewer_verified' => 'An independent receiving device verified house-only video/audio, including buffers/VOD.',
];
const STAGE_CHECKS = [
    'stage_zone_clear' => 'The full room capture zone is clear of private guests.',
    'stage_content_permitted' => 'Stage sources include only permitted host/performer content and no private screens or notifications.',
];

function capture_session_hash(): string
{
    return hash('sha256', csrf() . ':' . BOX2_VERSION);
}

function capture_assertions_valid(array $night): bool
{
    if (empty($_SESSION['admin']) || ($_SESSION['last_active'] ?? 0) < time()-1800
        || !hash_equals(capture_session_hash(), $night['capture_session_hash'])
        || !$night['capture_verified_at'] || strtotime($night['capture_verified_at']) < time()-1800) return false;
    return true;
}

function private_capture_safe(array $night): bool
{
    if (!capture_assertions_valid($night) || $night['room_transmission'] !== 'off' || $night['room_recording'] !== 'off') return false;
    $assertions=json_decode($night['capture_assertions'],true) ?: [];
    foreach (ROOM_OFF_CHECKS as $key=>$label) if (!flag($assertions,$key)) return false;
    if ($night['broadcast_source']==='off') return flag($assertions,'channel_stopped')===1;
    if ($night['broadcast_source']!=='house' || !config()['allow_house_continuity']) return false;
    foreach (HOUSE_CHECKS as $key=>$label) if (!flag($assertions,$key)) return false;
    return is_string($assertions['viewer_reference']??null) && trim($assertions['viewer_reference'])!=='';
}

function set_capture_state(int $nightId, array $data): void
{
    require_admin();
    $source=field($data,'source',10,true);
    if (!in_array($source,['off','stage','house','fault'],true)) throw new InvalidArgumentException('Unknown source state.');
    try {transaction(function () use ($nightId,$source,$data): void {
        if (!query('SELECT 1 FROM show_nights WHERE id=?',[$nightId])->fetchColumn()) throw new InvalidArgumentException('Show not found.');
        if ($source==='fault') {
            query("UPDATE show_nights SET recording_mode='unknown',broadcast_source='unknown',room_transmission='unknown',room_recording='unknown',capture_verified_at=NULL,capture_session_hash='',capture_assertions='{}' WHERE id=?",[$nightId]);
            audit('capture_fault_stop_required',(string)$nightId);return;
        }
        $assertions=[];
        if ($source==='stage') {
            if (query('SELECT 1 FROM show_nights WHERE private_room_occupied=1')->fetchColumn()
                || query("SELECT 1 FROM bookings WHERE status='checked_in' AND consent_level='private'")->fetchColumn()) {
                throw new InvalidArgumentException('Verify the private guest has left the capture zone before restoring any stage source.');
            }
            foreach (STAGE_CHECKS as $key=>$label) {
                if (!flag($data,$key)) throw new InvalidArgumentException('Reconfirm a clear capture zone and permitted stage content before restoring sources.');
                $assertions[$key]=1;
            }
        } else {
            foreach (ROOM_OFF_CHECKS as $key=>$label) {
                if (!flag($data,$key)) throw new InvalidArgumentException('Complete every room-off check. If uncertain, STOP STREAMING and recording.');
                $assertions[$key]=1;
            }
            if ($source==='off') {
                if (!flag($data,'channel_stopped')) throw new InvalidArgumentException('Confirm the channel and recording were stopped.');
                $assertions['channel_stopped']=1;
            } else {
                if (!config()['allow_house_continuity']) throw new InvalidArgumentException('House continuity is disabled pending separately approved real-device verification. Use full OFF fallback.');
                foreach (HOUSE_CHECKS as $key=>$label) {
                    if (!flag($data,$key)) throw new InvalidArgumentException('House isolation needs every check and independent viewer proof.');
                    $assertions[$key]=1;
                }
                $assertions['viewer_reference']=field($data,'viewer_reference',300,true);
            }
        }
        query('UPDATE show_nights SET recording_mode=?,recording_confirmed_at=?,broadcast_source=?,room_transmission=?,room_recording=?,capture_assertions=?,capture_session_hash=?,capture_verified_at=? WHERE id=?',
            [$source==='stage'?'public':'confirmed_off',utc(),$source,$source==='stage'?'on':'off',$source==='stage'?'allowed':'off',json_encode($assertions,JSON_THROW_ON_ERROR),capture_session_hash(),utc(),$nightId]);
        audit('capture_assertion_'.$source,(string)$nightId);
    });} catch (InvalidArgumentException $exception) {
        query("UPDATE show_nights SET recording_mode='unknown',broadcast_source='unknown',room_transmission='unknown',room_recording='unknown',capture_verified_at=NULL,capture_session_hash='',capture_assertions='{}' WHERE id=?",[$nightId]);
        throw $exception;
    }
}

function clear_private_room(int $nightId,array $data): void
{
    require_admin();
    if (!flag($data,'guest_left') || !flag($data,'capture_zone_clear')) throw new InvalidArgumentException('Confirm the guest left and the entire capture zone is clear.');
    transaction(function () use ($nightId): void {
        if (query("SELECT 1 FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.show_night_id=? AND b.status='checked_in' AND b.consent_level='private'",[$nightId])->fetchColumn()) {
            throw new InvalidArgumentException('Finish or cancel the checked-in set, then verify the guest has actually left.');
        }
        query("UPDATE show_nights SET private_room_occupied=0,recording_mode='unknown',broadcast_source='unknown',room_transmission='unknown',room_recording='unknown',capture_verified_at=NULL,capture_session_hash='',capture_assertions='{}' WHERE id=?",[$nightId]);
        audit('private_room_cleared_reverify',(string)$nightId);
    });
}
