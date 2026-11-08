package io.github.santiesc06.series76.data.voice

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

const val MAX_RECORDING_MS = 60_000 // the backend accepts up to 60 s (design V5)

/**
 * Records one voice message as AAC in an M4A file, mono, 16 kHz (design V7). The file lives in the
 * app's cache only until it is uploaded; the caller deletes it (V5: audio is not kept).
 */
@Singleton
class VoiceRecorder @Inject constructor(@ApplicationContext private val context: Context) {

    private var recorder: MediaRecorder? = null
    private var file: File? = null

    val isRecording: Boolean get() = recorder != null

    /** @param onLimit called (on the main thread) when the 60 s limit stops the recording. */
    fun start(onLimit: () -> Unit) {
        cancel()
        val target = File(context.cacheDir, "voice-message.m4a")
        val mediaRecorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
        try {
            mediaRecorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioChannels(1)
                setAudioSamplingRate(16_000)
                setAudioEncodingBitRate(32_000)
                setMaxDuration(MAX_RECORDING_MS)
                setOnInfoListener { _, what, _ ->
                    if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED) onLimit()
                }
                setOutputFile(target.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            mediaRecorder.release()
            target.delete()
            throw e
        }
        recorder = mediaRecorder
        file = target
    }

    /** Stops and returns the recording, or null if it was too short to contain any audio. */
    fun stop(): File? {
        val mediaRecorder = recorder ?: return null
        val target = file
        recorder = null
        file = null
        val ok = try {
            mediaRecorder.stop()
            true
        } catch (e: RuntimeException) {
            false // stop() throws when nothing was recorded (a very short tap)
        } finally {
            mediaRecorder.release()
        }
        if (!ok) target?.delete()
        return if (ok) target else null
    }

    fun cancel() {
        stop()?.delete()
    }
}
