package io.github.santiesc06.series76.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import io.github.santiesc06.series76.BuildConfig
import io.github.santiesc06.series76.data.api.Series76Api
import io.github.santiesc06.series76.data.auth.AuthInterceptor
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun json(): Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    @Provides
    @Singleton
    fun okHttp(auth: AuthInterceptor): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        // One agent turn takes ~3-8 s, up to ~30 s with a repair (design C3): no streaming.
        .readTimeout(60, TimeUnit.SECONDS)
        .addInterceptor(auth) // Bearer token on every request (US-21)
        .apply {
            // BASIC logs the method, URL and status only, never headers, so no token in logcat.
            if (BuildConfig.DEBUG) {
                addInterceptor(HttpLoggingInterceptor().setLevel(HttpLoggingInterceptor.Level.BASIC))
            }
        }
        .build()

    @Provides
    @Singleton
    fun api(client: OkHttpClient, json: Json): Series76Api = Retrofit.Builder()
        // From local.properties `api.baseUrl` (design M4); default http://10.0.2.2:8000/.
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(Series76Api::class.java)
}
