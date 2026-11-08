package io.github.santiesc06.series76.di

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStoreFile
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object StorageModule {

    /**
     * `files/datastore/auth.preferences_pb`: the login token (design U6). Excluded from cloud
     * backup and device transfer in `res/xml/backup_rules.xml` and `data_extraction_rules.xml`.
     */
    @Provides
    @Singleton
    fun authStore(@ApplicationContext context: Context): DataStore<Preferences> =
        PreferenceDataStoreFactory.create { context.preferencesDataStoreFile("auth") }
}
